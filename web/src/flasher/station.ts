/** One Station = one USB socket on the bench machine = one device slot.
 *
 *  NOTHING HERE TOUCHES A SERIAL PORT. Since decision 0023 every byte — the
 *  esptool phase and the device console both — is the bench agent's, and this
 *  module is the relay: it tells the agent which socket and what to do, and
 *  turns the agent's job log and console lines back into the events the run
 *  client feeds to the engine. The step LOGIC has always lived in the backend
 *  engine; what left is the Web Serial implementation underneath it.
 *
 *  What that bought, and why the browser version is gone rather than kept as a
 *  fallback: no port picker per unit (the V2's CH340 reports no USB serial
 *  number, so Chrome forgets the grant on every replug), no Chrome policy, no
 *  Web Serial at all — and a deploy can no longer break a bench mid-shift by
 *  invalidating the tab's lazily-loaded esptool chunk (prod run 6329). Python's
 *  esptool also changes baud on the open descriptor, where esptool-js reopened
 *  the port and reset the chip out from under its own stub.
 *
 *  The transport rules are still load-bearing (docs/flasher/design.md §7) and
 *  are now honoured by the agent: on the ESP32-C6's built-in USB-Serial/JTAG,
 *  `monitor_signals` is null and the agent leaves DTR/RTS alone, because the
 *  peripheral resets the chip on DTR=0 while RTS=1.
 */
import { API_URL } from "../api";
import { MarkAgent } from "./benchAgent";

/** The DTR/RTS line states the agent sets when it opens the console, sent as
 *  JSON to `POST /monitor/open`. The key names are Web Serial's on purpose —
 *  they are the wire contract the agent already reads (`agent.py`), and were
 *  kept when the browser stopped holding the port, so renaming them here breaks
 *  the other end silently. */
export interface OutputSignals {
  dataTerminalReady: boolean;
  requestToSend: boolean;
}

export interface TransportProfile {
  label: string;
  before: "default_reset" | "usb_reset";
  flash_baud: number;
  monitor_signals: OutputSignals | null;
  reenumerates_on_reset: boolean;
}

export const TRANSPORT_PROFILES: Record<string, TransportProfile> = {
  uart_bridge: {
    label: "external USB-UART bridge",
    before: "default_reset",
    flash_baud: 460800,
    monitor_signals: { dataTerminalReady: false, requestToSend: false },
    reenumerates_on_reset: false,
  },
  usb_serial_jtag: {
    label: "built-in USB-Serial/JTAG",
    before: "usb_reset",
    flash_baud: 115200, // CDC ignores baud; changing it only forces a pointless re-open
    monitor_signals: null, // NEVER call setSignals() — measured requirement
    reenumerates_on_reset: true,
  },
};

export interface FlashImage {
  url: string;
  address: string;
  filename: string;
  sha256: string;
  size: number;
}

export type LogDir = "app" | "err" | "tx" | "rx" | "esptool";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Firmware to the agent as base64: a 2.4 MB image is 3.2 MB on loopback. */
function bytesToBase64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000)
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}


/** Live stations, so an arriving port can go to the lowest-numbered one that
 *  has none. Without this every empty slot races for the same port. */
const STATIONS = new Set<Station>();



/** The operator's own name for a station, e.g. "left bench" or "Aqua line".
 *
 *  Naming the CABLE was the first attempt and it was the wrong object: the page
 *  cannot read a system port name anyway (`getInfo()` gives vendor and product
 *  id, nothing else), and what an operator actually points at is the station.
 *  The slot number stays visible underneath, so a renamed station is still
 *  addressable as "station 2" when something goes wrong.
 */
const NAME_KEY = "flasher.station-names.v1";
/** slot -> the USB socket it owns, e.g. "/dev/cu.usbserial-110". */
const SOCKET_KEY = "flasher.station-sockets.v1";

export function readStationSocket(slot: number): string {
  try {
    const all = JSON.parse(localStorage.getItem(SOCKET_KEY) ?? "{}") as Record<string, string>;
    return all[String(slot)] ?? "";
  } catch {
    return "";
  }
}

export function writeStationSocket(slot: number, node: string) {
  try {
    const all = JSON.parse(localStorage.getItem(SOCKET_KEY) ?? "{}") as Record<string, string>;
    if (node) all[String(slot)] = node;
    else delete all[String(slot)];
    localStorage.setItem(SOCKET_KEY, JSON.stringify(all));
  } catch {
    /* blocked storage: the mapping still holds for this session */
  }
}


/** Names are keyed by SLOT for the flashing bench and by the string "mark" for
 *  the marking one. Sharing the key would mean renaming flashing Station 1 also
 *  renamed the marking station, which is one bench reaching into another. */
export function readStationName(slot: number | string): string {
  try {
    const all = JSON.parse(localStorage.getItem(NAME_KEY) ?? "{}") as Record<string, string>;
    return all[String(slot)] ?? "";
  } catch {
    return "";
  }
}

export function writeStationName(slot: number | string, name: string) {
  try {
    const all = JSON.parse(localStorage.getItem(NAME_KEY) ?? "{}") as Record<string, string>;
    if (name.trim()) all[String(slot)] = name.trim();
    else delete all[String(slot)];
    localStorage.setItem(NAME_KEY, JSON.stringify(all));
  } catch {
    /* a name is a convenience, never state */
  }
}

export class Station {
  /** Which slot this is, 0-based. It is the key its socket is stored under. */
  slot = 0;
  profileKey = "uart_bridge";
  progress: number | null = null;
  lost = false;

  onEvent: (dir: LogDir, text: string) => void = () => {};
  /** Tell the UI the bench is waiting for a hand on the BOOT button, and when
   *  it stops. NOT a question: the operator may be reaching for the device, so
   *  the bench keeps trying rather than gating on an answer. */
  onBootWait: ((waiting: boolean) => void) | null = null;
  /** Set by the UI to stop waiting for BOOT. */
  cancelBootWait = false;
  onLine: (line: string) => void = () => {};
  onProgress: (pct: number | null) => void = () => {};

  /** The agent's console session, while one is open. */
  private monitorAgent: MarkAgent | null = null;
  private monitorSeen = 0;
  private monitorRunning = false;
  /** Set when esptool logged "Changing baudrate": the sync and the stub worked,
   *  and only the speed switch is in question. That tells the BOOT rung to drop
   *  to the ROM baud instead of waiting out the whole 30 s at a speed the board
   *  will not take. */

  emit(dir: LogDir, text: string) {
    this.onEvent(dir, text);
  }

  /** The socket this station owns — a real name off the machine, and the name
   *  of the SOCKET rather than of whatever is plugged into it. */
  get portLabel(): string {
    return this.socket || "—";
  }


  /** The socket this station owns, remembered across reloads. */
  get socket(): string {
    return readStationSocket(this.slot);
  }

  /** The node this station owns. Same as `socket` — kept as a name for the
   *  thing a run logs, since the station no longer has any other identity. */
  get node(): string {
    return this.socket;
  }

  /** The transport profile for this run.
   *
   *  It comes from the deployment VERSION (`transport_profile`), which the run
   *  client sets before step 1. There is no sniffing left: the old fallback
   *  read the USB ids off a SerialPort handle, and this tab no longer holds
   *  one. A bench trial with no version gets the bridge, which is what every
   *  V2 is; a C6 procedure names `usb_serial_jtag` itself. */
  profile(profileKey?: string): TransportProfile {
    const key = profileKey || this.profileKey;
    return TRANSPORT_PROFILES[key] ?? TRANSPORT_PROFILES.uart_bridge;
  }




  /** Give the cable back, on purpose.
   *
   *  The ONLY way a station loses its port. Everything else is sticky, so an
   *  arriving cable can never quietly move a slot out from under the operator.
   */
  /** Give up the port AND the socket. Freeing is how an operator moves a
   *  station to a different cable, so keeping the old socket would mean the
   *  station silently grabbed it back on the next replug. */
  unbind() {
    const was = this.socket;
    writeStationSocket(this.slot, "");
    this.emit("app", was ? `released ${was}` : "port freed");
  }

  register(slot: number) {
    this.slot = slot;
    STATIONS.add(this);
  }

  unregister() {
    STATIONS.delete(this);
  }

  /** Assign this station a socket BY NAME, from the agent's own list.
   *
   *  No `requestPort()`, so no Chrome picker and no serial permission: the
   *  operator chooses a `/dev/cu.*` node the agent can see, and the station
   *  owns that socket until it is freed (decision 0023).
   */
  assignSocket(node: string) {
    writeStationSocket(this.slot, node);
    this.emit("app", `station ${this.slot + 1} now owns ${node}`);
  }


  /** Does this slot have an assignment at all — a held port, or a remembered
   *  one whose device is simply not plugged in?
   *
   *  The distinction is the whole difference between "nobody has given this
   *  station a cable" and "its cable is not here right now", and showing the
   *  first when the second is true is how a station came to reclaim a port it
   *  had just reported as unassigned.
   */
  get assigned(): boolean {
    return !!this.socket;
  }

  /** Nothing to ask for: the agent owns the port and the socket IS the
   *  assignment. This is what removes the per-unit port picker. */
  async ensurePort(): Promise<void> {
    this.requireSocket();
  }


  /** Kept as a no-op: callers ask before a run, and there is no browser-side
   *  handle to re-acquire any more. */
  async resolvePort(): Promise<null> {
    return null;
  }



  // ---------------------------------------------------------------- esptool

  /** @param baudOverride use the ROM baud and skip the high-speed switch.
   *    Erase is a three-second command: raising the baud for it buys nothing
   *    and adds the one step that fails on a marginal cable or board — after
   *    "Changing baudrate to 460800" esptool itself warns that the chip may
   *    stop answering, which is exactly what happened on unit
   *    20:e7:c8:92:b6:10 (2026-09-16). Flashing keeps the high baud, where
   *    2.3 MB at 115200 would cost minutes.
   */

  /** Connect to the chip. The LADDER is the agent's now (`EspRun` in
   *  `agent.py`) and is the same one this file used to walk, rung for rung:
   *  the profile's baud, then 115200, then EN pulsed with the operator holding
   *  BOOT, retried until it answers or the deadline passes. Which rung worked
   *  comes back in `connect_mode`, prefixed `agent:`, so a unit that needs help
   *  is still visible in the run record rather than quietly rescued.
   */
  async espOpen(
    chipExpect: string,
    baudOverride?: number,
  ): Promise<{ chip: string; mac: string; connect_mode: string }> {
    const fast = baudOverride ?? this.profile().flash_baud;
    const info = await this.agentEsp("connect", { chip: chipExpect, baud: fast });
    return {
      chip: String(info.chip ?? ""),
      mac: String(info.mac ?? ""),
      connect_mode: `agent: ${String(info.connect_mode ?? "")}`,
    };
  }

  async espErase() {
    await this.agentEsp("erase", { baud: this.profile().flash_baud });
  }

  async espFlash(
    images: FlashImage[],
    flashConfig: Record<string, string>,
    _verifyMd5: boolean,
  ): Promise<void> {
    // The PAGE fetches the firmware — the agent holds no platform token and
    // makes no outbound connection — and hands the bytes over on loopback.
    const payload: { address: string; name: string; data: string }[] = [];
    for (const img of images) {
      const res = await fetch(`${API_URL}${img.url}`);
      if (!res.ok) throw new Error(`firmware fetch failed for ${img.filename}: ${res.status}`);
      const data = new Uint8Array(await res.arrayBuffer());
      if (data.length !== img.size)
        throw new Error(`${img.filename}: fetched ${data.length} B, platform stored ${img.size} B`);
      this.emit("app", `image ${img.filename} = ${data.length} bytes @ ${img.address}`);
      payload.push({ address: img.address, name: img.filename, data: bytesToBase64(data) });
    }
    await this.agentEsp("flash", {
      baud: this.profile().flash_baud,
      images: payload,
      flash_config: flashConfig,
    });
  }

  /** One ESP operation through the agent: the agent runs esptool on the
   *  station's socket, this tab relays its log and progress into the run. */
  private async agentEsp(op: string, extra: Record<string, unknown>): Promise<Record<string, unknown>> {
    const node = readStationSocket(this.slot);
    if (!node) throw new Error("this station has no socket assigned — Assign socket… first, the agent programs by socket");
    // The browser must not hold the port while the agent uses it.
    await this.cleanup();
    const agent = new MarkAgent();
    try {
      this.emit("app", `${op} through the agent on ${node}`);
      const r = await agent.esp({ op, port: node, ...extra }, (l) => {
        // "Writing at 0x00010000... (5 %)" — Python esptool puts a SPACE
        // before the percent sign where esptool-js did not, so the bar never
        // moved after the move to the agent (bench, 2026-09-17).
        const m = /\((\d+)\s*%\)/.exec(l.text);
        if (m) { this.progress = Number(m[1]); this.onProgress(this.progress); }
        this.emit((["app", "err", "esptool"].includes(l.dir) ? l.dir : "app") as LogDir, l.text);
      });
      if (r.status !== "pass") throw new Error(r.error ?? `${op} failed on the agent`);
      return r.info ?? {};
    } finally {
      this.progress = null;
      this.onProgress(null);
      agent.close();
    }
  }

  async espReset() {
    await this.agentEsp("reset", {});
  }
  /** A reset that re-enumerates USB is the agent's problem, not this tab's:
   *  the node reappears under the same name and the agent opens it again. */
  async awaitReenumerate(timeoutMs: number) {
    this.emit("app", "waiting for the device to come back (agent)");
    await sleep(Math.min(timeoutMs, 3000));
  }


  // ------------------------------------------------------- monitor serial

  async serialOpen(baud: number) {
    const node = this.requireSocket();
    const profile = this.profile();
    this.monitorAgent = new MarkAgent();
    await this.monitorAgent.monitorOpen(node, baud, profile.monitor_signals);
    this.monitorSeen = 0;
    this.emit("app", `monitor open on ${node} @ ${baud} (agent)`);
    this.monitorRunning = true;
    void this.pumpMonitor();
  }


  async serialClose() {
    this.monitorRunning = false;
    if (this.monitorAgent) {
      await this.monitorAgent.monitorClose().catch(() => {});
      this.monitorAgent.close();
      this.monitorAgent = null;
    }
    this.emit("app", "monitor closed (agent)");
  }

  /** Carry the device console into the run, one long poll after another.
   *
   *  NOT a timer. The engine drains its receive queue before every command and
   *  then waits for the reply, so a console delivered in clumps loses a reply
   *  that arrives between the two — measured on run 6377 (2026-09-17), where
   *  `SetOption153 0` was answered in 3 ms and the answer was never seen, and
   *  every other command paced at about a second. The agent holds the request
   *  until it has something to say, so a line reaches the engine in one local
   *  round trip.
   */
  private async pumpMonitor(): Promise<void> {
    const agent = this.monitorAgent;
    if (!agent) return;
    while (this.monitorRunning && this.monitorAgent === agent) {
      try {
        const r = await agent.monitorLines(this.monitorSeen, 10);
        if (!this.monitorRunning || this.monitorAgent !== agent) return;
        this.monitorSeen = r.seen;
        for (const line of r.lines) this.onLine(line);
        if (!r.open) return; // the session was closed under us
      } catch (e) {
        if (!this.monitorRunning) return;
        this.emit("err", `monitor poll: ${(e as Error).message}`);
        await sleep(250); // do not spin on a dead agent
      }
    }
  }

  private requireSocket(): string {
    const node = readStationSocket(this.slot);
    if (!node)
      throw new Error(
        "this station has no socket assigned — press Assign socket… first, "
        + "the agent addresses the port by its name",
      );
    return node;
  }

  async write(text: string) {
    if (!this.monitorAgent) throw new Error("monitor serial not open");
    await this.monitorAgent.monitorWrite(text);
  }

  /** Ask the device who it is, with no run in progress.
   *
   *  The marking bench does this the moment a device appears, so the operator
   *  reads the serial off the screen BEFORE pressing anything, and a press does
   *  not have to wait for the firmware to answer.
   *
   *  It asks exactly what the procedure's `wait_boot` asks — `Status` — which
   *  is why an answer here lets the run leave that step out. The run still
   *  reads the identity itself in its `command` step, so nothing is taken on
   *  trust: a device that has gone quiet in between fails there instead of
   *  waiting out a boot that already happened.
   *
   *  The reply is one line of Tasmota log with JSON after a prefix, so the
   *  brace is where parsing starts. Anything else on the wire is left alone and
   *  still reaches the log.
   */
  async probeIdentity(
    baud: number,
    cmd = "Status",
    expectKey = "Status",
    timeoutMs = 4000,
  ): Promise<Record<string, unknown>> {
    // Whatever this opens, it closes. The agent allows ONE console session at
    // a time, so a probe that stayed open would take the port away from the
    // run that follows it. It is a question, not a session.
    const wasOpen = !!this.monitorAgent;
    const prior = this.onLine;
    if (!wasOpen) await this.serialOpen(baud);
    const answer = new Promise<Record<string, unknown>>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.onLine = prior;
        reject(new Error(`the device did not answer "${cmd}" within ${timeoutMs / 1000}s`));
      }, timeoutMs);
      this.onLine = (line) => {
        prior(line);
        const brace = line.indexOf("{");
        if (brace < 0) return;
        try {
          const obj = JSON.parse(line.slice(brace)) as Record<string, unknown>;
          if (expectKey in obj) {
            clearTimeout(timer);
            this.onLine = prior;
            resolve(obj);
          }
        } catch {
          // A partial line, or one that is not JSON at all. Keep listening.
        }
      };
    });
    try {
      await this.write(`${cmd}\n`);
      return await answer;
    } finally {
      this.onLine = prior;
      if (!wasOpen) await this.serialClose().catch(() => {});
    }
  }

  /** In-monitor reset. Native USB needs the full USB-JTAG sequence and a
   *  re-open; a bridge just pulses RTS (wired to EN). */
  /** In-monitor reset: one EN pulse on the port the agent already holds. A
   *  device that re-enumerates comes back under the same node name, so this
   *  side only has to reopen — the old awaitReenumerate dance was about a
   *  SerialPort handle that no longer exists here. */
  async monitorReset(monitorBaud: number) {
    if (!this.monitorAgent) throw new Error("monitor serial not open");
    await this.monitorAgent.monitorReset();
    this.emit("app", "reset pulsed (agent)");
    if (this.profile().reenumerates_on_reset) {
      await this.serialClose();
      await sleep(2000);
      await this.serialOpen(monitorBaud);
    }
  }

  /** Let go of everything this station holds. The agent owns the port, so
   *  this is the console session and nothing else. */
  async cleanup() {
    await this.serialClose().catch(() => {});
  }
}
