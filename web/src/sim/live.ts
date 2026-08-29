/** A live simulation: an endless run you watch and interrupt.
 *
 *  The server solves at whatever rate it can and sends thirty frames a second
 *  carrying only two things — the LATEST value of everything the overlay
 *  draws, and closed min/max columns for the scopes. Nothing accumulates on
 *  the wire: at 1 us resolution the solver produces about 95,000 points a
 *  second and a frame is a few hundred bytes.
 *
 *  Frame layout (render/sim_worker.py):
 *    uint8 1 | float64 sim_t | float32 * overlay | uint16 n | { uint16 scope, float32 min, float32 max } * n
 */
import { API_URL } from "../api";

export interface LiveConfig {
  /** Which source to simulate, in the shape the relay expects. */
  target: Record<string, unknown>;
  /** Vector names to keep the latest value of, e.g. `v(/safety/so1)`. */
  overlay: string[];
  scopes: { vec: string; sim_s_per_px: number }[];
  /** Simulated seconds per second of wall clock. */
  speed: number;
  tstep: number;
}

export interface LiveState {
  status: "connecting" | "running" | "halted" | "stopped" | "error";
  simTime: number;
  /** Latest value per overlay vector name, in the order given in the config. */
  values: Float32Array;
  /** Closed scope columns, oldest first, capped to what a scope can show. */
  columns: { scope: number; min: number; max: number }[][];
  pointsPerSecond: number;
  message: string;
  /** Refs dropped from the netlist for having no model. */
  unmodelled: string[];
}

/** How many columns a scope keeps. Beyond this the oldest scroll off, which
 *  is what a scope does. */
const COLUMN_LIMIT = 600;

export class LiveSession {
  private socket: WebSocket | null = null;
  private readonly onChange: (s: LiveState) => void;
  private config: LiveConfig;
  state: LiveState;

  constructor(config: LiveConfig, onChange: (s: LiveState) => void) {
    this.config = config;
    this.onChange = onChange;
    this.state = {
      status: "connecting",
      simTime: 0,
      values: new Float32Array(config.overlay.length),
      columns: config.scopes.map(() => []),
      pointsPerSecond: 0,
      message: "",
      unmodelled: [],
    };
  }

  start(): void {
    const base = API_URL || window.location.origin;
    const url = new URL(`${base}/api/sim/live`, window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(url.toString());
    socket.binaryType = "arraybuffer";
    this.socket = socket;

    socket.onopen = () => {
      socket.send(JSON.stringify({
        ...this.config.target,
        tstep: this.config.tstep,
        speed: this.config.speed,
        overlay: this.config.overlay,
        scopes: this.config.scopes,
      }));
    };
    socket.onmessage = (event) => {
      if (typeof event.data === "string") this.onEvent(JSON.parse(event.data));
      else this.onFrame(event.data as ArrayBuffer);
    };
    socket.onerror = () => this.fail("the live session could not be reached");
    socket.onclose = () => {
      if (this.state.status !== "error") this.patch({ status: "stopped" });
    };
  }

  private onEvent(event: Record<string, unknown>): void {
    switch (event.ev) {
      case "ready":
        this.patch({ status: "running", message: "" });
        break;
      case "netlist":
        this.patch({ unmodelled: (event.unmodelled as string[]) ?? [] });
        break;
      case "rate":
        this.patch({ pointsPerSecond: (event.points_per_s as number) ?? 0 });
        break;
      case "error":
        this.fail(String(event.message ?? "the simulation failed"));
        break;
      case "log":
        // The worker's own stderr. Only interesting when something broke.
        this.patch({ message: String(event.message ?? "") });
        break;
      default:
        break;
    }
  }

  private onFrame(buffer: ArrayBuffer): void {
    const view = new DataView(buffer);
    if (view.getUint8(0) !== 1) return;
    const n = this.config.overlay.length;
    const simTime = view.getFloat64(1, true);
    const values = new Float32Array(n);
    for (let i = 0; i < n; i += 1) values[i] = view.getFloat32(9 + i * 4, true);

    let offset = 9 + n * 4;
    const count = view.getUint16(offset, true);
    offset += 2;
    const columns = this.state.columns.map((c) => c.slice());
    for (let i = 0; i < count; i += 1) {
      const scope = view.getUint16(offset, true);
      const min = view.getFloat32(offset + 2, true);
      const max = view.getFloat32(offset + 6, true);
      offset += 10;
      const list = columns[scope];
      if (!list) continue;
      list.push({ scope, min, max });
      if (list.length > COLUMN_LIMIT) list.splice(0, list.length - COLUMN_LIMIT);
    }
    this.patch({ simTime, values, columns });
  }

  private patch(next: Partial<LiveState>): void {
    this.state = { ...this.state, ...next };
    this.onChange(this.state);
  }

  private fail(message: string): void {
    this.patch({ status: "error", message });
  }

  private send(command: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(command));
    }
  }

  setSpeed(value: number): void {
    this.config = { ...this.config, speed: value };
    this.send({ op: "speed", value });
  }

  /** Change the circuit WHILE it runs — the point of a live session.
   *  `alter v1 = 3.3` on a source, `alter r7 = 1e9` to open a contact. */
  alter(command: string): void {
    this.send({ op: "alter", cmd: command });
  }

  halt(): void {
    this.send({ op: "halt" });
    this.patch({ status: "halted" });
  }

  resume(): void {
    this.send({ op: "resume" });
    this.patch({ status: "running" });
  }

  stop(): void {
    this.send({ op: "stop" });
    this.socket?.close();
    this.socket = null;
    this.patch({ status: "stopped" });
  }
}

// ------------------------------------------------------------------ sources

export interface LiveControl {
  /** SPICE instance name, lower case — what `alter` takes. */
  ref: string;
  /** `scripted` is a source the harness drives with a waveform. ngspice will
   *  not let one be steered mid-run, so it is listed to be findable, not to
   *  be turned. */
  kind: "source" | "passive" | "scripted";
  /** The value the netlist gave it, as written. */
  value: string;
  /** Parsed value where it is a plain number, for a slider. */
  numeric: number | null;
  unit: string;
}

const SI: Record<string, number> = {
  t: 1e12, g: 1e9, meg: 1e6, k: 1e3, m: 1e-3, u: 1e-6, n: 1e-9, p: 1e-12, f: 1e-15,
};

/** Read a SPICE value like `10k`, `100n`, `1e9`, `DC 24`. */
export function spiceValue(text: string): number | null {
  const m = /(-?\d*\.?\d+(?:e[-+]?\d+)?)\s*(meg|[tgkmunpf])?/i.exec(text.trim());
  if (!m) return null;
  const base = Number(m[1]);
  if (!Number.isFinite(base)) return null;
  const suffix = (m[2] ?? "").toLowerCase();
  return suffix ? base * (SI[suffix] ?? 1) : base;
}

/** The instances a live session can steer, read from the netlist it runs.
 *
 *  Sources first, because that is how a harness drives a circuit — a switch
 *  modelled with a control node is a source too, so toggling one is the same
 *  operation as changing a supply. Then plain passives, because opening a
 *  contact is `alter r7 = 1e9` and shorting it is `alter r7 = 1m`. */
export function liveControls(netlist: string): LiveControl[] {
  const out: LiveControl[] = [];
  // One entry per instance name. A flattened hierarchy can spell the same
  // reference twice, and `alter` on an ambiguous name is not a knob.
  const seen = new Set<string>();
  let inControl = false;
  for (const raw of netlist.split("\n")) {
    const line = raw.trim();
    // A `.control` block is ngspice's own scripting — `if`, `let`, `meas`.
    // Read as netlist lines its keywords look exactly like instances.
    if (/^\.control\b/i.test(line)) inControl = true;
    else if (/^\.endc\b/i.test(line)) inControl = false;
    if (inControl) continue;
    if (!line || line.startsWith("*") || line.startsWith(".") || line.startsWith("+")) continue;
    const parts = line.split(/\s+/);
    const ref = parts[0];
    const letter = ref[0]?.toLowerCase();
    if (!letter) continue;
    if (seen.has(ref.toLowerCase())) continue;
    if (letter === "v" || letter === "i") {
      seen.add(ref.toLowerCase());
      const rest = parts.slice(3).join(" ");
      const waveform = /\b(pwl|pulse|sin|exp|sffm|am)\b/i.exec(rest);
      if (waveform) {
        out.push({
          ref: ref.toLowerCase(), kind: "scripted", value: waveform[1].toUpperCase(),
          numeric: null, unit: letter === "v" ? "V" : "A",
        });
        continue;
      }
      const dc = /\bdc\s+(\S+)/i.exec(rest);
      const value = dc ? dc[1] : (parts[3] ?? "");
      out.push({
        ref: ref.toLowerCase(), kind: "source", value,
        numeric: spiceValue(value), unit: letter === "v" ? "V" : "A",
      });
    } else if (letter === "r" || letter === "c" || letter === "l") {
      seen.add(ref.toLowerCase());
      const value = parts[3] ?? "";
      out.push({
        ref: ref.toLowerCase(), kind: "passive", value,
        numeric: spiceValue(value),
        unit: letter === "r" ? "Ω" : letter === "c" ? "F" : "H",
      });
    }
  }
  return out;
}
