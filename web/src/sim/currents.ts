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
import type { SimPlot } from "./payload";

export interface NetCurrents {
  /** Wire id -> signed current per segment, along pts[i] -> pts[i+1]. */
  segments: Map<string, number[]>;
  /** Current INTO the device at each pin, keyed `${ref}.${pin}`. */
  pins: Map<string, number>;
  /** Nets that could not be resolved, and why — shown, never hidden. */
  unresolved: { net: string; reason: string }[];
}

const key = (x: number, y: number) => `${Math.round(x * 1000)},${Math.round(y * 1000)}`;

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
  plot: SimPlot,
  pinsOfRef: Map<string, SimPin[]>,
): number | null {
  const data = plot.currents.get(pin.ref.toLowerCase());
  if (!data) return null;
  const siblings = pinsOfRef.get(pin.ref) ?? [];
  if (siblings.length !== 2) return null; // no per-terminal current for these
  if (pin.pin !== "1" && pin.pin !== "2") return null;
  return pin.pin === "1" ? 1 : -1;
}

export function solveSegmentCurrents(
  geom: SimGeometry,
  plot: SimPlot,
  sample: number,
): NetCurrents {
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
    if (!group.wires.length) continue;

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
    if (!edges.length) continue;

    // Injections: current flowing from each device into the wire.
    const inject = new Map<string, number>();
    const unknownNodes: string[] = [];
    let known = 0;
    for (const pin of geom.pins) {
      if (pin.group !== group.id) continue;
      const node = key(pin.at[0], pin.at[1]);
      addNode(node);
      const sign = pinInjection(pin, plot, pinsOfRef);
      if (sign === null) {
        unknownNodes.push(node);
        continue;
      }
      const data = plot.currents.get(pin.ref.toLowerCase());
      const value = data ? data[Math.min(data.length - 1, Math.max(0, sample))] : 0;
      const intoDevice = sign * value;
      pins.set(`${pin.ref}.${pin.pin}`, intoDevice);
      inject.set(node, (inject.get(node) ?? 0) - intoDevice);
      known -= intoDevice;
    }
    if (unknownNodes.length === 1) {
      // Conservation names the last unknown.
      inject.set(unknownNodes[0], (inject.get(unknownNodes[0]) ?? 0) - known);
    } else if (unknownNodes.length > 1) {
      unresolved.push({
        net: group.net ?? group.id,
        reason: `${unknownNodes.length} terminals on this net have no current of their own`,
      });
      continue;
    }
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
