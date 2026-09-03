/** The editor's document as a SPICE netlist, made HERE, in the browser.
 *
 *  This exists for one reason: latency. The old live-edit path was autosave →
 *  server rewrites the file → kicad-cli exports a netlist (under QEMU on a
 *  Mac, the slowest step by a wide margin) → a new run from t = 0. For a
 *  sketch we own every byte — the palette's `Sim.*` fields, the wires, the
 *  labels — so the netlist can be written in under a millisecond and handed
 *  straight to the running worker. kicad-cli remains the authority for
 *  project sheets, which we do not own.
 *
 *  Node names are LOWERCASE from the start. ngspice lowercases internally, so
 *  the run's vectors are lowercase whichever way we spell them — emitting them
 *  lowercase means the names here, in the frames, and in the server geometry
 *  (`group.spice`) are one vocabulary with no case folding at the seams.
 *
 *  State carry: every capacitor and inductor card can take an `IC=%IC_ref%`
 *  token. The WORKER fills those from the halted run's last data point — it is
 *  the one holding the numbers — and `.tran ... uic` makes ngspice start from
 *  them instead of re-solving an operating point. That is what lets a charged
 *  cap be unwired, dragged elsewhere, rewired, and still be charged: the state
 *  is keyed to the REFERENCE, not to the node it used to sit on.
 */
import type { LibSymbol } from "../draw/types";
import { symbolPins, spiceName, type SchDoc } from "./doc";

export interface DocNetlist {
  text: string;
  /** Element name (lower case) -> its node names, in pin order. */
  nodesOf: Map<string, string[]>;
  /** What the worker must measure before the swap: one entry per part that
   *  carries state, with the OLD nodes it sat between. */
  state: { ref: string; kind: "c" | "l"; a: string; b: string }[];
  /** Vector name of every net, for the overlay: `v(<node>)`. */
  nets: string[];
  /** `ref.pin` -> the node it landed on. What the NEXT netlist uses to keep
   *  a surviving net's name, so vectors and scope traces outlive an edit. */
  pinNode: Map<string, string>;
}

/** The include line's placeholder. The real path is the render server's to
 *  know — a browser has no business carrying server filesystem layout, and a
 *  netlist that names an arbitrary path is refused there anyway. */
export const SIM_LIB_TOKEN = "%SIGMA_SIM_LIB%";

const keyOf = (x: number, y: number) => `${Math.round(x * 1000)},${Math.round(y * 1000)}`;

class Union {
  private parent = new Map<string, string>();

  find(k: string): string {
    let root = this.parent.get(k) ?? k;
    if (!this.parent.has(k)) this.parent.set(k, k);
    while (root !== (this.parent.get(root) ?? root)) root = this.parent.get(root)!;
    let at = k;
    while (at !== root) {
      const next = this.parent.get(at)!;
      this.parent.set(at, root);
      at = next;
    }
    return root;
  }

  join(a: string, b: string): void {
    this.parent.set(this.find(a), this.find(b));
  }
}

function fieldOf(sym: { fields: Record<string, string> }, lib: LibSymbol | undefined, name: string): string {
  const own = sym.fields[name];
  if (own !== undefined) return own;
  return lib?.props.find((f) => f.k === name)?.v ?? "";
}

/** `Sim.Params` text -> ordered `KEY=value` pairs, as written. */
function paramPairs(params: string): string {
  return params.trim().replace(/\s+/g, " ");
}

export function netlistDoc(
  doc: SchDoc,
  libs: Record<string, LibSymbol>,
  opts: {
    tstep: number;
    tstop: number;
    /** Emit IC tokens and ask for `uic` — a reload carrying state across. */
    carryState?: boolean;
    /** A node name this net already had, so vectors survive an edit. Given
     *  the net's member pins, returns the old name or null. */
    reuse?: (pins: { ref: string; pin: string }[]) => string | null;
  },
): DocNetlist {
  const dsu = new Union();
  // Wires join their endpoints; a wire end in the middle of another segment
  // is already a junction in the document (autoJunctions), and junction
  // points share coordinates, so coordinate identity is connectivity.
  for (const w of doc.wires) {
    for (let i = 0; i + 1 < w.pts.length; i += 1) {
      dsu.join(keyOf(w.pts[i][0], w.pts[i][1]), keyOf(w.pts[i + 1][0], w.pts[i + 1][1]));
    }
  }
  /** Join a point to every segment that passes THROUGH it, endpoint or not.
   *  Two callers need this: junction dots, whose whole meaning is "a wire end
   *  in the middle of another wire", and LABELS — a label names the wire it
   *  sits on, and people put labels mid-segment far more often than on an
   *  end. Missing that renamed `/in` to `net-_u1-pad1_` silently, measured on
   *  the worked example's own labels. */
  const attach = (x: number, y: number) => {
    const k = keyOf(x, y);
    for (const w of doc.wires) {
      for (let i = 0; i + 1 < w.pts.length; i += 1) {
        const [a, b] = [w.pts[i], w.pts[i + 1]];
        const within =
          Math.abs((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])) < 1e-6 &&
          x >= Math.min(a[0], b[0]) - 1e-6 && x <= Math.max(a[0], b[0]) + 1e-6 &&
          y >= Math.min(a[1], b[1]) - 1e-6 && y <= Math.max(a[1], b[1]) + 1e-6;
        if (within) dsu.join(k, keyOf(a[0], a[1]));
      }
    }
    return k;
  };
  for (const j of doc.junctions) attach(j[0], j[1]);

  interface PinAt { ref: string; pin: string; node: string; power: boolean; powerName: string }
  const pinsAt: PinAt[] = [];
  for (const sym of doc.symbols) {
    const lib = libs[sym.lib_id];
    const ref = sym.fields.Reference ?? "";
    const power = !!lib?.power;
    const powerName = power ? (fieldOf(sym, lib, "Value") || "0") : "";
    for (const p of symbolPins(sym, libs)) {
      // attach(), not keyOf() alone: a pin dropped onto the MIDDLE of a wire
      // is connected — that is how dragging a part onto a live circuit joins
      // it, mid-drag, the way Falstad joins posts that meet.
      pinsAt.push({ ref, pin: p.n, node: dsu.find(attach(p.at[0], p.at[1])), power, powerName });
    }
  }

  // ---- name the nets. Power value wins (ground's value is literally `0`,
  // which IS ngspice's ground node); then a label; then a name the last
  // netlist used for the same pins; then the first pin, KiCad-fashion.
  const names = new Map<string, string>();
  for (const l of doc.labels) {
    const node = dsu.find(attach(l.at[0], l.at[1]));
    if (!names.has(node)) {
      names.set(node, (l.kind === "global" ? "" : "/") + l.text.toLowerCase());
    }
  }
  for (const p of pinsAt) {
    if (p.power) names.set(p.node, p.powerName.toLowerCase() === "gnd" ? "0" : p.powerName.toLowerCase());
  }
  const members = new Map<string, { ref: string; pin: string }[]>();
  for (const p of pinsAt) {
    if (p.power) continue;
    const list = members.get(p.node) ?? [];
    list.push({ ref: p.ref, pin: p.pin });
    members.set(p.node, list);
  }
  // A name may be claimed ONCE per build. Reuse resurrects a net's old name
  // by pin membership — and a pin that LEFT a net still remembers it, so a
  // severed op-amp's floating output pin would reclaim "/ampout" while the
  // labelled wire keeps it too. Two nodes, one name: SPICE merges them, and
  // the part goes on driving a wire it is visibly not connected to — the
  // drawing says severed, the voltage keeps swinging. Labels and power names
  // are claimed first (they own their names); reuse gets what is left.
  const used = new Set(names.values());
  // Biggest net first: when a part is dragged off, its floating pins and the
  // net they left BOTH remember the old name, and whichever is asked first
  // wins it. The net that kept most of the membership is the one the name
  // means — a lone severed pin must lose the argument, or the surviving
  // net's traces die of a rename while the runaway pin carries the name off.
  const ordered = [...members.entries()].sort((a, b) => b[1].length - a[1].length);
  for (const [node, list] of ordered) {
    if (names.has(node)) continue;
    const reused = opts.reuse?.(list);
    if (reused && !used.has(reused)) {
      names.set(node, reused);
      used.add(reused);
      continue;
    }
    const first = [...list].sort((a, b) => a.ref.localeCompare(b.ref))[0];
    let name = `net-_${first.ref.toLowerCase()}-pad${first.pin}_`;
    while (used.has(name)) name += "_";
    names.set(node, name);
    used.add(name);
  }
  const nameOf = (node: string) => names.get(node) ?? node;

  // ---- element cards
  const cards: string[] = [];
  const models: string[] = [];
  const nodesOf = new Map<string, string[]>();
  const state: DocNetlist["state"] = [];
  let needsLib = false;

  for (const sym of doc.symbols) {
    const lib = libs[sym.lib_id];
    if (!lib || lib.power) continue;
    const ref = (sym.fields.Reference ?? "").trim();
    if (!ref || ref.startsWith("#")) continue;
    const device = fieldOf(sym, lib, "Sim.Device").trim().toUpperCase();
    const params = paramPairs(fieldOf(sym, lib, "Sim.Params"));
    const value = fieldOf(sym, lib, "Value").trim();
    const pins = symbolPins(sym, libs);
    const nodes = pins.map((p) => {
      const at = pinsAt.find((x) => x.ref === ref && x.pin === p.n);
      return at ? nameOf(at.node) : "0";
    });
    const name = spiceName(sym, libs); // RSW1 for a switch drawn SW1
    nodesOf.set(name, nodes);

    if (device === "SUBCKT") {
      // Port order IS the Sim.Pins order; the pins list is already in pin
      // number order and Sim.Pins was derived from it (`sch_lib._ic`).
      const model = fieldOf(sym, lib, "Sim.Name").trim();
      cards.push(`x${name} ${nodes.join(" ")} ${model}${params ? " " + params : ""}`);
      needsLib = true;
      continue;
    }
    if (device === "D") {
      const modelName = `d__${name}`;
      // `spiceName` already prefixed the device letter when the reference
      // needed one — a diode drawn D1 is ALREADY "d1", and prepending another
      // letter ("dd1") runs fine but under a name the geometry does not know:
      // dead current readout, dead charge dots, dead alter.
      cards.push(`${name.startsWith("d") ? name : `d${name}`} ${nodes.join(" ")} ${modelName}`);
      models.push(`.model ${modelName} D(${params})`);
      continue;
    }
    if (device === "R") {
      // A switch: its resistance lives in Sim.Params, its Value is the state.
      const r = /(?:^|\s)r=(\S+)/i.exec(params)?.[1] ?? value ?? "1G";
      cards.push(`${name} ${nodes.join(" ")} ${r}`);
      continue;
    }
    const letter = name[0];
    if (letter === "c" || letter === "l") {
      state.push({ ref: name, kind: letter, a: nodes[0] ?? "0", b: nodes[1] ?? "0" });
      const ic = opts.carryState ? ` IC=%IC_${name}%` : "";
      cards.push(`${name} ${nodes.join(" ")} ${value}${ic}`);
      continue;
    }
    // R, V, I and anything else SPICE builds from the Value field.
    cards.push(`${name} ${nodes.join(" ")} ${value}`);
  }

  const pinNode = new Map<string, string>();
  for (const p of pinsAt) {
    if (!p.power) pinNode.set(`${p.ref}.${p.pin}`, nameOf(p.node));
  }
  const nets = [...new Set([...names.values()])].filter((n) => n !== "0");
  const lines = [
    ".title sketch (browser netlist)",
    ...(needsLib ? [`.include "${SIM_LIB_TOKEN}"`] : []),
    ...cards,
    ...models,
    // rshunt keeps a FLOATING charged cap solvable — unwire one and it is a
    // two-node island, which is a singular matrix without a path to ground.
    ".options savecurrents rshunt=1e12",
    `.tran ${opts.tstep} ${opts.tstop}${opts.carryState ? " uic" : ""}`,
    ".end",
  ];
  return { text: lines.join("\n") + "\n", nodesOf, state, nets, pinNode };
}
