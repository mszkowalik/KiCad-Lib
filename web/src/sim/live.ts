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

/** One scope. `vec` names a vector the run has; `terms` asks for a weighted
 *  SUM of vectors instead — how a wire's or a terminal's current is expressed,
 *  since ngspice has no vector for either. */
export interface LiveScopeSpec {
  vec: string;
  sim_s_per_px: number;
  terms?: { vec: string; coeff: number }[];
}

export interface LiveConfig {
  /** Which source to simulate, in the shape the relay expects. */
  target: Record<string, unknown>;
  /** A netlist the editor wrote itself. Skips kicad-cli on the server, which
   *  is most of what makes a sketch's live mode feel instant. */
  netlist?: string;
  /** Vector names to keep the latest value of, e.g. `v(/safety/so1)`. */
  overlay: string[];
  scopes: LiveScopeSpec[];
  /** Simulated seconds per second of wall clock. */
  speed: number;
  tstep: number;
  /** The scope pixel pitch, so the worker can keep min/max HISTORY for every
   *  overlay vector and hand a newly opened trace its own past. */
  historySpan?: number;
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
  /** Every vector this run has, as ngspice named them. It is what says which
   *  devices answer for a branch current, which decides how a wire or a pin
   *  current can be expressed. */
  vectors: string[];
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
      vectors: [],
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
        ...(this.config.netlist ? { netlist: this.config.netlist } : {}),
        tstep: this.config.tstep,
        speed: this.config.speed,
        overlay: this.config.overlay,
        scopes: this.config.scopes,
        history_span: this.config.historySpan ?? 0,
      }));
      // Whatever was asked for while this was still connecting, in order and
      // after the start frame — the worker reads that one first and refuses
      // anything before it.
      const queued = this.pending;
      this.pending = [];
      for (const command of queued) socket.send(JSON.stringify(command));
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
        this.patch({
          status: "running",
          message: "",
          vectors: ((event.vectors as string[]) ?? []).map((v) => v.toLowerCase()),
        });
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
    // Frame v2 carries its own overlay count: a reload can change the overlay
    // while frames closed against the old list are still in flight, and a
    // frame must be sliced by what IT holds, not by what the config now says.
    if (view.getUint8(0) !== 2) return;
    const simTime = view.getFloat64(1, true);
    const n = view.getUint16(9, true);
    const expected = this.config.overlay.length;
    const values = new Float32Array(expected);
    for (let i = 0; i < Math.min(n, expected); i += 1) values[i] = view.getFloat32(11 + i * 4, true);

    let offset = 11 + n * 4;
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

  /** A command, now or as soon as the socket opens.
   *
   *  It used to be dropped silently when the socket was still connecting, and
   *  that is exactly when the page sends: the effect that creates the session
   *  and the one that tells it which scopes to watch run in the same commit,
   *  microseconds apart and long before the handshake finishes. So a live run
   *  opened with a trace already picked watched nothing at all.
   */
  private send(command: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(command));
      return;
    }
    if (this.socket && this.socket.readyState === WebSocket.CONNECTING) {
      this.pending.push(command);
    }
  }

  private pending: Record<string, unknown>[] = [];

  /** Change what the scopes watch, without restarting the run.
   *
   *  Columns are addressed by POSITION in this list, so a scope list that
   *  changes shape moves every trace's history one slot along. Carry it over
   *  by NAME: a trace that is still watched keeps what it has collected, and
   *  only a new one starts empty.
   *
   *  Dropping the lot instead — which this used to do — meant that removing
   *  one trace blanked every OTHER trace on the page, because the whole scope
   *  went back to zero columns and the plots had nothing left to draw.
   *
   *  Frames already in flight were closed against the old list, so for about
   *  one round trip a column can land in the wrong slot. That is one or two
   *  columns out of six hundred, against a history that would otherwise be
   *  thrown away entirely.
   */
  setScopes(scopes: LiveScopeSpec[]): void {
    const was = this.config.scopes;
    // Carry a trace's history only when the vec AND the pixel pitch match: a
    // speed change alters sim-seconds-per-column, and old columns kept under
    // a new pitch draw the past at the wrong timebase. Dropped history is
    // reseeded by the worker's backlog, which resets on the same change.
    const kept = scopes.map((s) => {
      const at = was.findIndex((old) => old.vec === s.vec && old.sim_s_per_px === s.sim_s_per_px);
      return at >= 0 ? this.state.columns[at] ?? [] : [];
    });
    this.config = { ...this.config, scopes };
    this.send({
      op: "scopes",
      // `backlog` marks the scopes this side holds NO columns for — the
      // worker seeds those from its history so they open full, and must not
      // seed the ones whose columns survived the list change.
      scopes: scopes.map((s, i) => ({ ...s, backlog: !(kept[i]?.length) })),
      history_span: scopes[0]?.sim_s_per_px ?? this.config.historySpan ?? 0,
    });
    this.patch({ columns: kept });
  }

  /** Swap the running circuit for an edited one, keeping component state.
   *
   *  The worker fills each `%IC_<ref>%` token from the part's own last
   *  reading, so a charged cap stays charged across the edit. Scope columns
   *  are carried by vec name, the same as `setScopes` — an edit that keeps a
   *  trace keeps its history.
   */
  reload(payload: {
    netlist: string;
    state: { ref: string; kind: "c" | "l"; a: string; b: string }[];
    overlay: string[];
    scopes: LiveScopeSpec[];
  }): void {
    const was = this.config.scopes;
    const kept = payload.scopes.map((s) => {
      const at = was.findIndex((old) => old.vec === s.vec && old.sim_s_per_px === s.sim_s_per_px);
      return at >= 0 ? this.state.columns[at] ?? [] : [];
    });
    this.config = {
      ...this.config,
      netlist: payload.netlist,
      overlay: payload.overlay,
      scopes: payload.scopes,
    };
    this.send({
      op: "reload",
      ...payload,
      scopes: payload.scopes.map((s, i) => ({ ...s, backlog: !(kept[i]?.length) })),
      history_span: payload.scopes[0]?.sim_s_per_px ?? this.config.historySpan ?? 0,
    });
    this.patch({ columns: kept });
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
