/** Where the current in each wire SEGMENT comes from.
 *
 *  SPICE returns currents through DEVICES, never through wires. Falstad can
 *  animate a wire because its solver knows the whole graph; we have to work it
 *  out from the terminal currents, and two facts make that exact rather than a
 *  guess:
 *
 *  1. The wire graph of one net is almost always a TREE. On a tree, Kirchhoff
 *     fixes every segment: the current in the edge above a subtree is the sum
 *     of what the subtree injects. A net whose wires form a loop is genuinely
 *     undetermined, and is reported as such instead of being drawn wrong.
 *  2. A net may carry ONE terminal whose current we do not have — a ground
 *     symbol, a supply rail, one pin of a subcircuit. Conservation supplies
 *     it: the injections around a net sum to zero. Two unknowns on one net
 *     cannot be separated, and that net is left unanimated.
 */
import type { SimGeometry, SimPin } from "../api";
import { plotReader, type SampleReader, type SimPlot } from "./payload";

export interface NetCurrents {
  /** Wire id -> signed current per segment, along pts[i] -> pts[i+1]. */
  segments: Map<string, number[]>;
  /** Current INTO the device at each pin, keyed `${ref}.${pin}`. */
  pins: Map<string, number>;
  /** Nets that could not be resolved, and why — shown, never hidden. */
  unresolved: { net: string; reason: string }[];
}

const key = (x: number, y: number) => `${Math.round(x * 1000)},${Math.round(y * 1000)}`;

/** What the RUN calls each drawn part. A switch drawn `SW1` is `rsw1` in the
 *  netlist (`Sim.Device` prefixes the reference), and the run reports currents
 *  under the element name — asking for `sw1` returns null, which silently
 *  turned every switch terminal into an unknown and zeroed its whole net. */
function elementOf(geom: SimGeometry): (ref: string) => string {
  const map = new Map(geom.symbols.map((s) => [s.ref, (s.spice || s.ref).toLowerCase()]));
  return (ref) => map.get(ref) ?? ref.toLowerCase();
}

interface Edge {
  wireId: string;
  index: number;
  a: string;
  b: string;
}

/** Current flowing from the wire INTO the device at this pin, when it is
 *  known. SPICE's sign convention for a two-terminal element is that a
 *  positive `i` flows from its first node, through the element, to its
 *  second — so pin 1 drains the wire and pin 2 feeds it. */
function pinInjection(
  pin: SimPin,
  reader: SampleReader,
  pinsOfRef: Map<string, SimPin[]>,
  el: (ref: string) => string,
): number | null {
  if (reader.current(el(pin.ref)) === null) return null;
  const siblings = pinsOfRef.get(pin.ref) ?? [];
  if (siblings.length !== 2) return null; // no per-terminal current for these
  if (pin.pin !== "1" && pin.pin !== "2") return null;
  return pin.pin === "1" ? 1 : -1;
}

export function solveSegmentCurrents(geom: SimGeometry, reader: SampleReader): NetCurrents {
  const el = elementOf(geom);
  const pinsOfRef = new Map<string, SimPin[]>();
  for (const pin of geom.pins) {
    const list = pinsOfRef.get(pin.ref);
    if (list) list.push(pin);
    else pinsOfRef.set(pin.ref, [pin]);
  }

  const wiresById = new Map(geom.wires.map((w) => [w.id, w]));
  const segments = new Map<string, number[]>();
  const pins = new Map<string, number>();
  const unresolved: { net: string; reason: string }[] = [];

  for (const group of geom.groups) {

    // Nodes and edges of this net's wire graph.
    const edges: Edge[] = [];
    const adjacency = new Map<string, { edge: number; to: string }[]>();
    const addNode = (k: string) => {
      if (!adjacency.has(k)) adjacency.set(k, []);
    };
    for (const wireId of group.wires) {
      const wire = wiresById.get(wireId);
      if (!wire) continue;
      segments.set(wireId, new Array(Math.max(0, wire.pts.length - 1)).fill(0));
      for (let i = 0; i + 1 < wire.pts.length; i += 1) {
        const a = key(wire.pts[i][0], wire.pts[i][1]);
        const b = key(wire.pts[i + 1][0], wire.pts[i + 1][1]);
        addNode(a);
        addNode(b);
        const index = edges.length;
        edges.push({ wireId, index: i, a, b });
        adjacency.get(a)?.push({ edge: index, to: b });
        adjacency.get(b)?.push({ edge: index, to: a });
      }
    }
    // Injections: current flowing from each device into the wire.
    const inject = new Map<string, number>();
    const unknownNodes: string[] = [];
    /** The terminals with no current of their own, so that a net with exactly
     *  one of them can name it by conservation. An op-amp output, a regulator
     *  pin, any leg of a subcircuit: SPICE gives no per-terminal current for
     *  those, and this is the only way to plot one. */
    const unknownPins: SimPin[] = [];
    let known = 0;
    for (const pin of geom.pins) {
      if (pin.group !== group.id) continue;
      const node = key(pin.at[0], pin.at[1]);
      addNode(node);
      const sign = pinInjection(pin, reader, pinsOfRef, el);
      if (sign === null) {
        unknownNodes.push(node);
        unknownPins.push(pin);
        continue;
      }
      const intoDevice = sign * (reader.current(el(pin.ref)) ?? 0);
      pins.set(`${pin.ref}.${pin.pin}`, intoDevice);
      inject.set(node, (inject.get(node) ?? 0) - intoDevice);
      known -= intoDevice;
    }
    if (unknownNodes.length === 1) {
      // Conservation names the last unknown. The injections around a net sum
      // to zero, so what this terminal puts INTO the wire is minus what the
      // rest put in — and the current INTO the device is `known` itself.
      inject.set(unknownNodes[0], (inject.get(unknownNodes[0]) ?? 0) - known);
      const lone = unknownPins[0];
      if (lone) pins.set(`${lone.ref}.${lone.pin}`, known);
    } else if (unknownNodes.length > 1) {
      unresolved.push({
        net: group.net ?? group.id,
        reason: `${unknownNodes.length} terminals on this net have no current of their own`,
      });
      continue;
    }
    // A net with no wires still has its PIN currents on record — that is how
    // a severed terminal reads 0 instead of vanishing from the scope. There
    // is just nothing left to route.
    if (!edges.length) continue;
    if (edges.length >= adjacency.size) {
      unresolved.push({
        net: group.net ?? group.id,
        reason: "the wires form a loop, so the split between them is undetermined",
      });
      continue;
    }

    // Root the tree anywhere and push subtree sums up the edges.
    const start = adjacency.keys().next().value as string | undefined;
    if (!start) continue;
    const order: { node: string; parent: string | null; edge: number | null }[] = [];
    const seen = new Set<string>([start]);
    const stack = [{ node: start, parent: null as string | null, edge: null as number | null }];
    while (stack.length) {
      const item = stack.pop();
      if (!item) break;
      order.push(item);
      for (const link of adjacency.get(item.node) ?? []) {
        if (seen.has(link.to)) continue;
        seen.add(link.to);
        stack.push({ node: link.to, parent: item.node, edge: link.edge });
      }
    }
    const subtree = new Map<string, number>();
    for (let i = order.length - 1; i >= 0; i -= 1) {
      const item = order[i];
      const total = (subtree.get(item.node) ?? 0) + (inject.get(item.node) ?? 0);
      subtree.set(item.node, total);
      if (item.parent !== null && item.edge !== null) {
        subtree.set(item.parent, (subtree.get(item.parent) ?? 0) + total);
        const edge = edges[item.edge];
        // `total` flows from the child towards the parent. Express it along
        // the segment's own direction, a -> b.
        const childIsB = edge.b === item.node;
        const list = segments.get(edge.wireId);
        if (list) list[edge.index] = childIsB ? -total : total;
      }
    }
  }
  return { segments, pins, unresolved };
}


// ------------------------------------------------- a wire's current OVER TIME

/** The name a wire's own current carries on the scope.
 *
 *  It is not a SPICE vector and never can be — ngspice knows device branches,
 *  not wires. This is the reconstruction above, evaluated at every sample, and
 *  the name says so: `iw(` is a wire, `i(` is a device.
 */
export const wireTrace = (wireId: string) => `iw(${wireId})`;

/** The name a PIN's current carries. Same reasoning: `ip(` is a terminal that
 *  SPICE does not report, worked out from the net around it. */
export const pinTrace = (ref: string, pin: string) => `ip(${ref}.${pin})`;

export interface Probe {
  name: string;
  kind: "wire" | "pin";
  /** A wire id, or `${ref}.${pin}`. */
  id: string;
}

export function probeOf(name: string): Probe | null {
  if (name.startsWith("iw(") && name.endsWith(")")) {
    return { name, kind: "wire", id: name.slice(3, -1) };
  }
  if (name.startsWith("ip(") && name.endsWith(")")) {
    return { name, kind: "pin", id: name.slice(3, -1) };
  }
  return null;
}

/** How many solves one request may cost. Above it the run is sampled at a
 *  stride and the gaps are filled by straight lines — the plot is drawn at
 *  screen resolution anyway, and a wire current is a reconstruction, not a
 *  reading, so a straight line between two solved points is no worse than the
 *  solver's own assumption about the wire between two pins. */
const SOLVE_BUDGET = 3000;

/** Each named wire's current across a whole finished run.
 *
 *  Built on demand — nothing here runs until someone puts a wire on the scope —
 *  and for every requested wire at once, because the expensive half is the
 *  per-sample solve and it produces all of them together.
 */
export function solveProbeSeries(
  geom: SimGeometry,
  plot: SimPlot,
  probes: Probe[],
): Map<string, Float64Array> {
  const out = new Map<string, Float64Array>();
  const n = plot.scale.length;
  if (!probes.length || !n) return out;
  for (const probe of probes) out.set(probe.name, new Float64Array(n));

  const stride = Math.max(1, Math.ceil(n / SOLVE_BUDGET));
  const marks: number[] = [];
  for (let i = 0; i < n; i += stride) marks.push(i);
  if (marks[marks.length - 1] !== n - 1) marks.push(n - 1);

  for (const at of marks) {
    const solved = solveSegmentCurrents(geom, plotReader(plot, at));
    for (const probe of probes) {
      out.get(probe.name)![at] = readProbe(solved, probe);
    }
  }
  if (stride > 1) {
    for (const probe of probes) {
      const series = out.get(probe.name)!;
      for (let m = 0; m + 1 < marks.length; m += 1) {
        const a = marks[m];
        const b = marks[m + 1];
        const span = b - a;
        for (let i = 1; i < span; i += 1) {
          series[a + i] = series[a] + ((series[b] - series[a]) * i) / span;
        }
      }
    }
  }
  return out;
}


/** One probe's reading out of a solved frame. */
export function readProbe(solved: NetCurrents, probe: Probe): number {
  if (probe.kind === "pin") {
    const v = solved.pins.get(probe.id);
    return v === undefined ? NaN : v;
  }
  const list = solved.segments.get(probe.id);
  return list && list.length ? list[0] : NaN;
}


// ------------------------------------------- a probe as a SUM OF DEVICE CURRENTS

export interface Term {
  /** Device reference, lower case — what the run calls its branch. */
  ref: string;
  coeff: number;
}

/** A probe written as a linear combination of device currents.
 *
 *  The reconstruction above is LINEAR in the terminal currents: a segment
 *  carries the sum of what the subtree below it injects, and a lone unknown
 *  terminal is minus the sum of the known ones. So the coefficients can be
 *  read off by solving once per device with a reader that says "this one is
 *  1 A, everything else is 0" — no algebra to get wrong, and it is the same
 *  solver either way.
 *
 *  It is worth the trouble because it moves a probe from the BROWSER, which
 *  sees thirty frames a second, into the WORKER, which sees every point the
 *  solver takes. A wire current sampled at frame rate comes out as a staircase
 *  next to the voltage on the same net; expressed as terms, it is drawn from
 *  the same points as the voltage and is exactly as smooth.
 *
 *  Returns null when the probe cannot be resolved at all — a net with two
 *  unknown terminals, or a loop.
 */
export function probeTerms(
  geom: SimGeometry,
  probe: Probe,
  /** Does the run report a branch current for this device? The basis has to
   *  keep the same NULLS the run has: a device the run cannot answer for is
   *  what makes a terminal the unknown one, and answering 0 for it instead
   *  would solve a different circuit. */
  hasCurrent: (ref: string) => boolean,
): Term[] | null {
  const el = elementOf(geom);
  const group = probe.kind === "pin"
    ? geom.pins.find((x) => `${x.ref}.${x.pin}` === probe.id)?.group
    : geom.groups.find((g) => g.wires.includes(probe.id))?.id;
  if (!group) return null;
  const members = geom.pins.filter((x) => x.group === group && !x.power);
  // The solver's own rule, applied up front: a terminal is unknown when its
  // device reports no current the way a two-pin element does. ONE unknown is
  // named by conservation; two cannot be separated, and the segments come
  // back as their pre-filled zeros — a coefficient read off that is a silent
  // 0, not a NaN, so the count has to be checked here rather than inferred.
  const pinsPerRef = new Map<string, number>();
  for (const pin of geom.pins) pinsPerRef.set(pin.ref, (pinsPerRef.get(pin.ref) ?? 0) + 1);
  const unknown = members.filter((x) =>
    !hasCurrent(el(x.ref)) || pinsPerRef.get(x.ref) !== 2 || (x.pin !== "1" && x.pin !== "2"));
  if (unknown.length > 1) return null;
  const elements = Array.from(new Set(members.map((x) => el(x.ref))));
  const terms: Term[] = [];
  for (const name of elements) {
    if (!hasCurrent(name)) continue;
    const unit: SampleReader = {
      position: 0,
      scaleType: "time",
      voltage: () => null,
      current: (asked) => {
        const key = asked.toLowerCase();
        if (!hasCurrent(key)) return null;
        return key === name ? 1 : 0;
      },
    };
    const coeff = readProbe(solveSegmentCurrents(geom, unit), probe);
    if (!Number.isFinite(coeff)) return null;
    if (Math.abs(coeff) > 1e-12) terms.push({ ref: name, coeff });
  }
  return terms.length ? terms : null;
}
