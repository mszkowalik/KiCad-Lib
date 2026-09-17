/** One Station = one USB serial adapter = one device slot.
 *
 *  Port of the proven PoC (clients/flasher-poc/station.js, hardware-verified
 *  2026-07-26): esptool-js flashing over Web Serial AND the monitor byte pipe
 *  on the same port. The step LOGIC lives in the backend engine — this module
 *  only executes `action` messages and pipes console lines.
 *
 *  The transport rules are load-bearing (docs/flasher/design.md §7): on the
 *  ESP32-C6's built-in USB-Serial/JTAG, never call setSignals() in monitor
 *  mode — the peripheral resets the chip on DTR=0 while RTS=1, and a reset
 *  re-enumerates the USB device, killing the SerialPort handle.
 */
import { ESPLoader, Transport } from "esptool-js";
import { md5 } from "js-md5";
import { API_URL } from "../api";
import { listSerialPorts } from "./benchAgent";

export interface TransportProfile {
  label: string;
  before: "default_reset" | "usb_reset";
  flash_baud: number;
  monitor_signals: SerialOutputSignals | null;
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

export const USB_SERIAL_JTAG = { vendorId: 0x303a, productId: 0x1001 };

export function autoProfile(port: SerialPort | null): string {
  const info = port?.getInfo?.() ?? {};
  return info.usbVendorId === USB_SERIAL_JTAG.vendorId &&
    info.usbProductId === USB_SERIAL_JTAG.productId
    ? "usb_serial_jtag"
    : "uart_bridge";
}

export interface FlashImage {
  url: string;
  address: string;
  filename: string;
  sha256: string;
  size: number;
}

export type LogDir = "app" | "err" | "tx" | "rx" | "esptool";

const enc = new TextEncoder();
const dec = new TextDecoder();
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** The ROM bootloader's own speed. Always works; everything faster is an
 *  optimisation that a marginal board or cable can refuse. */
const ROM_BAUD = 115200;

/** How long the bench keeps retrying while it waits for BOOT to be held.
 *  Long enough to pick the device up, short enough that a station cannot sit on
 *  a run: after this it FAILS, and the operator starts it again. */
const BOOT_WAIT_MS = 30_000;

/** esptool-js imports its chip module lazily; after a deploy the hashed chunk
 *  this tab knows about no longer exists, and the browser throws this. It is a
 *  page fault, never a device one. */
function isStaleChunk(e: Error): boolean {
  return /dynamically imported module|Importing a module script failed/i.test(e.message);
}

function staleChunkError(e: Error): Error {
  return new Error(
    "this page is out of date — the platform was updated while it was open, and it can no "
    + `longer load the esptool chip module. Reload the page and run again. (${e.message})`,
  );
}

/** Await something, but never longer than `ms`.
 *
 *  Every step of closing a serial port can hang rather than fail: a writer
 *  whose stream never drains, a cancel the device never acknowledges, a read
 *  loop still parked in read(). One hang there means `port.close()` is never
 *  reached, the port stays open on the browser side, and the NEXT device
 *  cannot be opened at all. Losing a close is recoverable; not reaching the
 *  close is not.
 */
async function within<T>(ms: number, work: Promise<T> | undefined): Promise<"ok" | "timeout"> {
  if (!work) return "ok";
  let timer: ReturnType<typeof setTimeout>;
  const expired = new Promise<"timeout">((r) => {
    timer = setTimeout(() => r("timeout"), ms);
  });
  try {
    return await Promise.race([work.then(() => "ok" as const).catch(() => "ok" as const), expired]);
  } finally {
    clearTimeout(timer!);
  }
}

/** Which live Station holds which port.
 *
 *  Identity cannot come from USB: every V2 dongle is the same CH340
 *  (0x1A86:0x7523) and every C6 the same native USB device (0x303A:0x1001), so
 *  `getInfo()` cannot tell two slots' devices apart. Re-acquiring by USB ids
 *  alone would therefore let one slot match — and then try to open — the port
 *  another slot is mid-run on. A station only ever takes a port that no other
 *  station holds.
 */
const CLAIMED = new Map<SerialPort, Station>();

/** Live stations, so an arriving port can go to the lowest-numbered one that
 *  has none. Without this every empty slot races for the same port. */
const STATIONS = new Set<Station>();

/** "#1=station 2, #2=free" — who holds which port, for the log.
 *
 *  Exists because every V2 dongle reports the same USB ids, so a claim dispute
 *  cannot be read off the labels. The index is the port's place in getPorts().
 */
function claimTable(ports: SerialPort[]): string {
  if (!ports.length) return "no granted ports";
  return ports
    .map((p, i) => {
      const holder = CLAIMED.get(p);
      return `#${i + 1}=${holder ? `station ${holder.slot + 1}` : "free"}`;
    })
    .join(", ");
}


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

/** Which node a granted port turned out to be, once identified.
 *
 *  Keyed by the SerialPort object, which Chrome mints fresh on every replug —
 *  so a new object is identified again, which is exactly right: it may be a
 *  different socket. */
const NODE_OF = new WeakMap<SerialPort, string>();

/** Identification opens a port, so two at once would make the answer
 *  ambiguous: both would appear as "newly held". They queue. */
let identifyQueue: Promise<unknown> = Promise.resolve();

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

/** Which `/dev/cu.*` node this SerialPort actually is.
 *
 *  THE TRICK, and the only one that works: Web Serial tells a page nothing but
 *  the USB ids, which every V2 dongle shares. The agent can see the real nodes
 *  and, from lsof, which process holds each. So: note what is held, OPEN the
 *  port, and look again — the node that just became held is this port. Neither
 *  side could answer it alone.
 *
 *  It costs one open, which pulses DTR/RTS and therefore RESETS an attached
 *  ESP32. That is why it never runs against a busy station, and why the result
 *  is cached per port object.
 *
 *  Returns "" when the agent is not running, which is not an error: the bench
 *  then works by hand, it just cannot remember which socket is which.
 */
export async function identifyPort(port: SerialPort): Promise<string> {
  const cached = NODE_OF.get(port);
  if (cached) return cached;
  const run = identifyQueue.then(async () => {
    const held = async () =>
      new Set((await listSerialPorts()).filter((p) => p.held_by).map((p) => p.device));
    let before: Set<string>;
    try {
      before = await held();
    } catch {
      return ""; // no agent
    }
    try {
      await port.open({ baudRate: ROM_BAUD });
    } catch {
      return ""; // already open, or gone
    }
    try {
      const after = await listSerialPorts();
      const node = after.find((p) => p.held_by && !before.has(p.device))?.device ?? "";
      if (node) NODE_OF.set(port, node);
      return node;
    } catch {
      return "";
    } finally {
      await port.close().catch(() => {});
    }
  });
  identifyQueue = run.catch(() => "");
  return run;
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
  /** Which slot this is, 0-based. Decides who takes an unclaimed port. */
  slot = 0;
  /** Where this port sat in the last getPorts() list, for the label. */
  portIndex = -1;
  port: SerialPort | null = null;
  portIds: Partial<SerialPortInfo> = {};
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

  private transport: Transport | null = null;
  private loader: ESPLoader | null = null;
  /** Set when esptool logged "Changing baudrate": the sync and the stub worked,
   *  and only the speed switch is in question. That tells the BOOT rung to drop
   *  to the ROM baud instead of waiting out the whole 30 s at a speed the board
   *  will not take. */
  private sawBaudChange = false;
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private writer: WritableStreamDefaultWriter<Uint8Array> | null = null;
  private readerTask: Promise<void> | null = null;
  private rxBuf = "";
  private closing = false;
  private partialTimer: ReturnType<typeof setTimeout> | undefined;
  private reappeared: (() => void) | null = null;

  emit(dir: LogDir, text: string) {
    this.onEvent(dir, text);
  }

  /** What this station's port is called, as far as the browser allows.
   *
   *  Every V2 dongle answers with the same USB ids, so the ids alone cannot
   *  tell two stations' ports apart — which is how a refused assignment looked
   *  like a port jumping between stations. The `#n` is the port's place in
   *  getPorts(), the only per-port distinction the API offers.
   */
  get portLabel(): string {
    if (!this.port) return this.socket || "—";
    // The NODE when the agent identified it: that is a real name the operator
    // can read off the machine, and it names the socket rather than the device.
    const node = NODE_OF.get(this.port);
    if (node) return node;
    const i = this.port.getInfo();
    if (!i.usbVendorId) return "serial port (agent not running)";
    const ids = `${i.usbVendorId.toString(16).padStart(4, "0")}:${(i.usbProductId ?? 0)
      .toString(16)
      .padStart(4, "0")}`;
    return `USB ${ids} · unidentified`;
  }

  /** The socket this station owns, remembered across reloads. */
  get socket(): string {
    return readStationSocket(this.slot);
  }

  /** The node the held port turned out to be, or "". */
  get node(): string {
    return (this.port && NODE_OF.get(this.port)) || "";
  }

  profile(profileKey?: string): TransportProfile {
    const key = profileKey || this.profileKey || autoProfile(this.port);
    return TRANSPORT_PROFILES[key] ?? TRANSPORT_PROFILES.uart_bridge;
  }

  /** Take a port for this station, releasing whatever it held before.
   *
   *  Refuses a port another station already holds. Without that refusal the
   *  registry is only advisory, and two slots could end up pointing at one
   *  cable — which is exactly what happened when four stations mounted at once
   *  and React's double-invoke interleaved their adopt/release cycles.
   */
  private claim(port: SerialPort): boolean {
    const holder = CLAIMED.get(port);
    if (holder && holder !== this) return false;
    if (this.port && this.port !== port && CLAIMED.get(this.port) === this)
      CLAIMED.delete(this.port);
    this.port = port;
    this.portIds = port.getInfo();
    CLAIMED.set(port, this);
    return true;
  }

  /** Drop a port this station no longer owns.
   *
   *  The registry is the single truth about who holds what; a station's own
   *  `port` field is a cache of it. Any interleaving that leaves the two
   *  disagreeing is repaired here rather than being rendered.
   */
  private healOwnership() {
    if (this.port && CLAIMED.get(this.port) !== this) {
      this.port = null;
      this.portIds = {};
      this.portIndex = -1;
    }
  }

  /** True when no OTHER station holds this port. */
  private free(port: SerialPort): boolean {
    const holder = CLAIMED.get(port);
    return holder === undefined || holder === this;
  }

  release() {
    if (this.port && CLAIMED.get(this.port) === this) CLAIMED.delete(this.port);
    this.port = null;
    this.portIds = {};
    this.portIndex = -1;
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
    this.release();
    this.emit("app", was ? `released ${was}` : "port freed");
  }

  register(slot: number) {
    this.slot = slot;
    STATIONS.add(this);
  }

  unregister() {
    STATIONS.delete(this);
    this.release();
  }

  async requestPort() {
    const picked = await navigator.serial.requestPort();
    const ports = await navigator.serial.getPorts();
    // Every assign records the WHOLE picture, because the interesting failure
    // is "this port is taken" and the only way to argue with that is to see
    // which station holds which port. USB ids cannot distinguish them.
    this.emit("app", `claims: ${claimTable(ports)} | picked #${ports.indexOf(picked) + 1}`);
    const holder = CLAIMED.get(picked);
    if (holder && holder !== this) {
      throw new Error(
        `that port (#${ports.indexOf(picked) + 1} of ${ports.length}) is already assigned to ` +
          `station ${holder.slot + 1} — free it there first`,
      );
    }
    this.claim(picked);
    this.portIndex = ports.indexOf(picked);
    // Assigning is the moment the station learns its SOCKET. Everything after
    // this — a replug, a reload — is matched on the node, never on order.
    const node = await identifyPort(picked);
    if (node) {
      writeStationSocket(this.slot, node);
      this.emit("app", `port granted: ${node} — station ${this.slot + 1} now owns this socket`);
    } else {
      this.emit(
        "app",
        "port granted, but the agent is not running — this station cannot remember its socket",
      );
    }
  }

  /** Is the device actually on the bus right now? */
  get live(): boolean {
    return !!this.port && (this.port as { connected?: boolean }).connected !== false;
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
    return !!this.port || !!this.socket;
  }

  /** A live port for this run, asking the operator only when it has to.
   *
   *  On a bench with a serial policy the grant is already there and this is
   *  silent. On any OTHER machine — a customer's, one nobody can configure —
   *  a CH340 has no serial number, so Chrome discards the grant with the
   *  device and there is no way to avoid one pick per unit. That is the
   *  baseline the bench has to work well under, not a failure.
   *
   *  MUST be called from the operator's own click: requestPort() needs a user
   *  gesture, and a gesture does not survive an intervening fetch. Ask for the
   *  port BEFORE creating the run, never after.
   */
  async ensurePort(): Promise<SerialPort> {
    await this.resolvePort();
    const live = (p: SerialPort) => (p as { connected?: boolean }).connected !== false;
    if (this.port && live(this.port)) return this.port;
    this.emit("app", "no granted port for this device — asking the operator to pick it");
    await this.requestPort();
    if (!this.port) throw new Error("no port picked");
    return this.port;
  }

  /** Re-acquire a LIVE SerialPort for this station's device.
   *
   *  A handle does NOT survive the device leaving the bus. After a replug
   *  Chrome hands out a new SerialPort object from getPorts(), and open() on
   *  the old one fails with "Failed to execute 'open' on 'SerialPort': Failed
   *  to open serial port." — which is what an operator sees when they swap one
   *  device for the next. The grant survives, so this needs no popup: every
   *  open path calls this first, and re-picking the port by hand is never the
   *  answer to that error.
   */
  async resolvePort(): Promise<SerialPort | null> {
    if (!navigator.serial) return this.port;
    this.healOwnership();
    const ports = await navigator.serial.getPorts();
    this.healOwnership(); // another station may have claimed while we awaited
    // `connected` is the ONLY liveness signal. Being present in getPorts() is
    // not one: the spec hands back the same SerialPort instance for a device
    // across a disconnect, so an object that can never be opened again stays
    // in that list. Checking membership was the first attempt at this fix and
    // it changed nothing, because membership was always true.
    const live = (p: SerialPort) => (p as { connected?: boolean }).connected !== false;
    // Only speak when there is something to say. A slot with no port and no
    // hint has nothing to report, and four stations each logging their idleness
    // twice — React runs effects twice in development — buries the one line
    // that matters when a port really does go missing.
    const expectsAPort = !!this.port;
    if (expectsAPort)
      this.emit(
        "app",
        `granted ports: ${ports.length}; held=${this.port ? "yes" : "no"} ` +
          `live=${this.port ? live(this.port) : "-"} ` +
          `states=[${ports.map((p) => (live(p) ? "live" : "dead")).join(",")}] ` +
          `claims: ${claimTable(ports)}`,
      );
    if (this.port && live(this.port) && this.free(this.port)) return this.port;
    // Held but DEAD: the device left the bus, and Chrome mints a NEW
    // SerialPort object on the replug rather than reviving the old one
    // (measured 2026-09-16: `held=yes live=false states=[live] claims:
    // #1=free`). The old object can never be opened again, so the station must
    // take the replacement — via the slot's own hint below, never by USB ids,
    // which every V2 dongle shares.
    if (this.port && !live(this.port)) {
      this.emit("app", "held port is dead — looking for its replacement");
      this.release();
    }
    if (this.port) return this.port;

    // BY SOCKET. A station owns a physical USB socket, and takes the port that
    // IS that socket — never the next one to turn up. Arrival order lived here
    // until 2026-09-16 and was always a guess: it handed station 1 whatever
    // appeared, so moving a cable silently moved the station. The agent makes
    // the real answer available (docs/reference/bench-serial-ports.md).
    const socket = this.socket;
    if (!socket) return null; // never assigned: nothing to adopt, by design
    const candidates = ports.filter((p) => live(p) && !CLAIMED.has(p));
    for (const p of candidates) {
      // Identifying opens the port, so never while this station is working.
      if (this.transport !== null || this.reader !== null) break;
      if ((await identifyPort(p)) !== socket) continue;
      this.claim(p);
      this.portIndex = ports.indexOf(p);
      this.lost = false;
      this.emit("app", `${socket} is back — station ${this.slot + 1} took it`);
      return this.port;
    }
    if (expectsAPort || candidates.length)
      this.emit("app", `${socket} is not on the bus`);
    return null;
  }

  /** Clear a half-open port before opening it.
   *
   *  Chrome can be left believing a port is still open after the device left
   *  the bus: the OS descriptor IS released (nothing holds /dev/cu.* and it
   *  opens fine from a shell — measured 2026-09-16), but the renderer's
   *  SerialPort stays half-open and the next open() throws "Failed to execute
   *  'open' on 'SerialPort': Failed to open serial port." Closing first costs
   *  nothing when the port really is closed: that throws, which is the normal
   *  case and is why this swallows.
   */
  private async settlePort() {
    if (!this.port) return;
    try {
      await this.port.close();
      this.emit("app", "port was still open on the browser side — closed it first");
    } catch {
      /* already closed — the expected case */
    }
  }

  attachPort(port: SerialPort) {
    this.claim(port);
    this.emit("app", `port attached (previously granted): ${this.portLabel}`);
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
  /** Put the chip in download mode ourselves, for a board whose auto-reset
   *  cannot.
   *
   *  The operator holds BOOT, which grounds IO0; this pulses EN through RTS,
   *  and the chip comes up in download mode and STAYS there. esptool is then
   *  told `no_reset`, because its own sequence — seven attempts, each a reset —
   *  is what knocks such a board back out again. Proven on unit
   *  20:e7:c8:92:b6:10 (2026-09-16), which fails every reset sequence and syncs
   *  first time this way.
   */
  private async pulseEnable() {
    if (!this.port) throw new Error("no port");
    await this.settlePort();
    await this.port.open({ baudRate: ROM_BAUD });
    try {
      await this.port.setSignals({ dataTerminalReady: false, requestToSend: true });
      await sleep(200);
      await this.port.setSignals({ dataTerminalReady: false, requestToSend: false });
      await sleep(400);
      this.emit("app", "EN pulsed while BOOT is held — chip should be in download mode");
    } finally {
      await this.port.close();
    }
  }

  /** Connect to the chip, escalating until something works.
   *
   *  Every rung exists because a real V2 needed it (2026-09-16):
   *
   *  1. `default_reset` at the profile's baud — a healthy board, 40 s flash.
   *  2. `default_reset` at 115200 — a board or cable that cannot survive
   *     esptool-js changing speed, which it does by CLOSING and REOPENING the
   *     port, toggling DTR/RTS and resetting the chip out from under the stub.
   *  3. `no_reset` after pulsing EN ourselves, with the operator holding BOOT —
   *     a board whose IO0 is not driven, where every reset esptool runs puts it
   *     back into flash boot. Seven retries make this WORSE, not better. This
   *     rung keeps the profile's baud, and falls back to 115200 only if the
   *     speed switch itself is what fails.
   *
   *  Rung 3 needs a human, so it asks (`onNeedBoot`) rather than failing. The
   *  rung that worked is returned, so a unit that needed help is visible in the
   *  run record instead of being quietly rescued every time.
   */
  /** The connect ladder. Every rung is a device fault it was built for — but a
   *  failure to LOAD esptool's chip module is not a rung, it is a stale page
   *  after a deploy, and it aborts the ladder with the one fix that exists. */
  async espOpen(
    chipExpect: string,
    baudOverride?: number,
  ): Promise<{ chip: string; mac: string; connect_mode: string }> {
    const fast = baudOverride ?? this.profile().flash_baud;
    const rungs: { baud: number; boot: boolean; why: string }[] = [
      { baud: fast, boot: false, why: `${fast} baud` },
      ...(fast === ROM_BAUD ? [] : [{ baud: ROM_BAUD, boot: false, why: "115200, no baud change" }]),
      { baud: fast, boot: true, why: "BOOT held, no_reset" },
    ];
    let last: Error | null = null;
    for (const rung of rungs) {
      // The BOOT rung KEEPS TRYING. The operator has to pick the device up and
      // hold a button, which takes longer than one connect attempt, so asking
      // once and failing would just move the retry into their hands. It ends on
      // success, on Cancel, or at the deadline — never silently.
      if (rung.boot) {
        this.cancelBootWait = false;
        this.onBootWait?.(true);
        this.emit("app", "waiting for the BOOT button to be held — retrying until it is");
        const deadline = performance.now() + BOOT_WAIT_MS;
        // Start fast. A board that needs BOOT held is not automatically a board
        // that cannot take 460800 — those are two different faults, and paying
        // three minutes of 115200 for every unit on the chance that they travel
        // together is the wrong trade. If the speed switch is what breaks, the
        // NEXT attempt drops to the ROM baud and stays there.
        let bootBaud = fast;
        try {
          for (let tryNo = 1; ; tryNo++) {
            if (this.cancelBootWait) throw new Error("waiting for BOOT was cancelled");
            const why = `${rung.why}, ${bootBaud} baud`;
            try {
              await this.pulseEnable();
              const out = await this.openAt(bootBaud, chipExpect, true);
              this.emit("app", `connected: ${why}, attempt ${tryNo}`);
              return { ...out, connect_mode: why };
            } catch (e) {
              last = e as Error;
              await this.cleanup();
              if (isStaleChunk(last)) throw staleChunkError(last);
              // Reaching "Changing baudrate" means the sync and the stub were
              // fine and only the speed switch failed — the one failure here
              // that holding BOOT harder will not fix.
              if (bootBaud !== ROM_BAUD && this.sawBaudChange) {
                bootBaud = ROM_BAUD;
                this.emit("app", `this board will not hold ${fast} baud — dropping to ${ROM_BAUD}`);
              }
              if (performance.now() > deadline)
                throw new Error(`BOOT was not held within ${BOOT_WAIT_MS / 1000}s`);
              if (tryNo % 4 === 0)
                this.emit("app", `still waiting for BOOT (attempt ${tryNo})`);
              await sleep(1200);
            }
          }
        } finally {
          this.onBootWait?.(false);
        }
      }
      try {
        const out = await this.openAt(rung.baud, chipExpect, false);
        this.emit("app", `connected: ${rung.why}`);
        return { ...out, connect_mode: rung.why };
      } catch (e) {
        last = e as Error;
        await this.cleanup();
        // Not a rung that failed — a page that cannot load esptool's chip
        // module any more. Walking the ladder would blame the device and end
        // in "BOOT was not held" (prod run 6329, 2026-09-17).
        if (isStaleChunk(last)) throw staleChunkError(last);
        this.emit("err", `${last.message} — ${rung.why} did not work`);
      }
    }
    throw last ?? new Error("could not connect to the device");
  }

  private async openAt(
    baud: number,
    chipExpect: string,
    bootHeld = false,
  ): Promise<{ chip: string; mac: string }> {
    await this.resolvePort();
    if (!this.port) throw new Error("no port");
    await this.settlePort();
    const profile = this.profile();
    const watch = (d: string) => {
      if (d.includes("Changing baudrate")) this.sawBaudChange = true;
    };
    const terminal = {
      clean: () => {},
      writeLine: (d: string) => {
        watch(d);
        this.emit("esptool", d);
      },
      write: (d: string) => {
        watch(String(d));
        const s = String(d).replace(/[\r\n]+$/, "");
        if (s.trim()) this.emit("esptool", s);
      },
    };
    this.transport = new Transport(this.port, false);
    this.transport.setDeviceLostCallback(() =>
      this.emit("err", "esptool: device lost (USB re-enumerated?)"),
    );
    this.loader = new ESPLoader({
      transport: this.transport,
      baudrate: baud,
      terminal,
      debugLogging: false,
    });
    this.emit(
      "app",
      `transport profile: ${profile.label} (before=${
        bootHeld ? "no_reset (BOOT held)" : profile.before
      }, baud=${baud})`,
    );
    // no_reset when the operator is holding BOOT: the chip is already in
    // download mode and every reset esptool would run risks losing it.
    this.sawBaudChange = false;
    const chip = await this.loader.main(bootHeld ? "no_reset" : profile.before);
    const mac = await (this.loader.chip as { readMac(l: ESPLoader): Promise<string> }).readMac(
      this.loader,
    );
    this.emit("app", `chip=${chip} mac=${mac}`);
    if (
      chipExpect &&
      !chip.toLowerCase().replace(/[-\s]/g, "").includes(chipExpect.toLowerCase().replace(/-/g, ""))
    ) {
      // The engine double-checks; reporting is enough here.
      this.emit("err", `release expects ${chipExpect}, device reports "${chip}"`);
    }
    return { chip, mac };
  }

  async espErase() {
    if (!this.loader) throw new Error("esptool not connected");
    await this.loader.eraseFlash();
  }

  async espFlash(
    images: FlashImage[],
    flashConfig: Record<string, string>,
    verifyMd5: boolean,
  ): Promise<void> {
    if (!this.loader) throw new Error("esptool not connected");
    const fileArray: { data: Uint8Array; address: number }[] = [];
    for (const img of images) {
      const res = await fetch(`${API_URL}${img.url}`);
      if (!res.ok) throw new Error(`firmware fetch failed for ${img.filename}: ${res.status}`);
      const data = new Uint8Array(await res.arrayBuffer());
      if (data.length !== img.size)
        throw new Error(`${img.filename}: fetched ${data.length} B, platform stored ${img.size} B`);
      this.emit("app", `image ${img.filename} = ${data.length} bytes @ ${img.address}`);
      fileArray.push({ data, address: parseInt(img.address, 16) });
    }
    type FlashOpts = Parameters<ESPLoader["writeFlash"]>[0];
    // "detect" has to be resolved HERE, not handed to esptool-js.
    //
    // esptool-js understands it in one place only — the image-header rewrite,
    // which calls detectFlashSize() itself. Its own fit check does not: it
    // passes the literal string to flashSizeBytes(), which looks for "KB" or
    // "MB", finds neither, returns -1, and then refuses EVERY image with
    // "File 1 doesn't fit in the available flash". The Python esptool that the
    // V2 procedures were reconstructed from accepts `--flash_size detect`, so
    // that string is what the deployment versions carry.
    let flashSize = (flashConfig.size ?? "keep") as FlashOpts["flashSize"];
    if (flashSize === "detect") {
      flashSize = (await this.loader.detectFlashSize()) as FlashOpts["flashSize"];
      this.emit("app", `flash size "detect" resolved to ${flashSize}`);
    }
    await this.loader.writeFlash({
      fileArray,
      flashMode: (flashConfig.mode ?? "keep") as FlashOpts["flashMode"],
      flashFreq: (flashConfig.freq ?? "keep") as FlashOpts["flashFreq"],
      flashSize,
      eraseAll: false,
      compress: true,
      reportProgress: (_i: number, written: number, total: number) => {
        this.progress = Math.round((written / total) * 100);
        this.onProgress(this.progress);
      },
      calculateMD5Hash: verifyMd5 ? (image: Uint8Array) => md5(image) : undefined,
    });
    this.progress = null;
    this.onProgress(null);
  }

  /** Deliberate hard reset: IO0 high (app boot, NOT download mode), pulse EN.
   *  esptool-js's after("hard_reset") alone is a no-op on both transports —
   *  it only releases an RTS the connect sequence already left deasserted
   *  (measured; see design.md §7). */
  private async hardResetPulse(holdMs = 150) {
    const sig = async (s: SerialOutputSignals) => {
      if (this.transport) {
        if ("dataTerminalReady" in s) await this.transport.setDTR(s.dataTerminalReady!);
        if ("requestToSend" in s) await this.transport.setRTS(s.requestToSend!);
      } else if (this.port) {
        await this.port.setSignals(s);
      }
    };
    try {
      await sig({ dataTerminalReady: false });
      await sig({ requestToSend: true });
      await sleep(holdMs);
      await sig({ requestToSend: false });
      this.emit("app", `hard reset pulse (DTR=0, RTS 1→0, hold ${holdMs}ms)`);
    } catch (e) {
      // Native USB: the device can vanish the instant it resets — success.
      this.emit("app", `reset pulse ended early: ${(e as Error).message} (device already rebooting)`);
    }
  }

  async espReset() {
    await this.hardResetPulse();
    try {
      await this.transport?.disconnect();
    } catch (e) {
      this.emit("app", `transport close after reset: ${(e as Error).message}`);
    }
    this.transport = null;
    this.loader = null;
  }

  // ------------------------------------------------- USB re-enumeration (C6)

  sameDevice(port: SerialPort | null): boolean {
    const a = this.portIds ?? this.port?.getInfo?.() ?? {};
    const b = port?.getInfo?.() ?? {};
    return a.usbVendorId === b.usbVendorId && a.usbProductId === b.usbProductId;
  }

  noteDisconnect(port: SerialPort): boolean {
    if (!this.sameDevice(port)) return false;
    this.lost = true;
    this.emit("app", "USB device left the bus");
    // Drop it HERE rather than waiting for something to notice it is dead.
    // Chrome mints a new SerialPort on the replug, so the object this station
    // holds is already worthless; keeping it only makes the station look bound
    // to a cable it can never open. The slot hint brings the replacement back.
    //
    // NOT during a run: an ESP32-C6 leaves the bus on every reset, and
    // `awaitReenumerate` is mid-flight waiting for that exact port to return.
    // Releasing under it would break the transport the run depends on.
    const busy = this.transport !== null || this.reader !== null;
    if (!busy && port === this.port) {
      this.release();
      this.emit("app", "held port dropped — the slot hint will take its replacement");
    }
    return true;
  }

  noteConnect(port: SerialPort): boolean {
    // ONLY this station's own port coming back. Matching on USB ids here was
    // another way for a slot to take a cable that was never its own, since
    // every V2 dongle answers with the same pair.
    if (port !== this.port) return false;
    this.lost = false;
    this.emit("app", "USB device back on the bus — fresh SerialPort handle");
    this.reappeared?.();
    return true;
  }

  async awaitReenumerate(timeoutMs: number) {
    if (!this.port) throw new Error("no port");
    this.portIds = Object.keys(this.portIds).length ? this.portIds : this.port.getInfo();
    const deadline = performance.now() + timeoutMs;
    const arrived = new Promise<void>((resolve) => {
      this.reappeared = resolve;
      setTimeout(resolve, Math.min(timeoutMs, 1500));
    });
    await arrived;
    this.reappeared = null;
    for (;;) {
      const ports = await navigator.serial.getPorts();
      const candidate: SerialPort =
        ports.find((p) => this.sameDevice(p) && this.free(p)) ?? this.port;
      try {
        await candidate.open({ baudRate: 115200 });
        await candidate.close();
        this.claim(candidate);
        this.emit("app", "port is openable again");
        return;
      } catch (e) {
        if (performance.now() > deadline)
          throw new Error(`device did not come back: ${(e as Error).message}`);
        await sleep(300);
      }
    }
  }

  // ------------------------------------------------------- monitor serial

  async serialOpen(baud: number) {
    if (!this.port) throw new Error("no port");
    if (this.reader) await this.serialClose();
    const profile = this.profile();
    await this.settlePort();
    for (let attempt = 1; ; attempt++) {
      try {
        await this.port!.open({ baudRate: baud, bufferSize: 8192 });
        break;
      } catch (e) {
        if (attempt >= 10)
          throw new Error(`could not open port at ${baud}: ${(e as Error).message}`);
        this.emit("app", `open attempt ${attempt} failed (${(e as Error).message}) — retrying`);
        await sleep(400);
        // Retrying the SAME handle is pointless once the device has left the
        // bus — re-acquire before every retry, not only on the first open.
        await this.resolvePort();
        await this.settlePort();
      }
    }
    if (profile.monitor_signals) {
      await this.port.setSignals(profile.monitor_signals);
      this.emit("app", `handshake lines set ${JSON.stringify(profile.monitor_signals)}`);
    } else {
      this.emit("app", "handshake lines left untouched (profile says do not drive DTR/RTS)");
    }
    this.writer = this.port.writable!.getWriter();
    this.reader = this.port.readable!.getReader();
    this.readerTask = this.readLoop();
    this.emit("app", `monitor serial open @ ${baud}`);
  }

  private async readLoop() {
    try {
      for (;;) {
        const { value, done } = await this.reader!.read();
        if (done) break;
        this.rxBuf += dec.decode(value, { stream: true });
        this.schedulePartialFlush();
        let nl;
        while ((nl = this.rxBuf.search(/\r?\n/)) >= 0) {
          const line = this.rxBuf.slice(0, nl);
          this.rxBuf = this.rxBuf.slice(nl + (this.rxBuf[nl] === "\r" ? 2 : 1));
          if (!line.trim()) continue;
          this.onLine(line);
        }
      }
    } catch (e) {
      if (!this.closing) this.emit("err", `read loop: ${(e as Error).message}`);
    }
  }

  /** A prompt or partial line without a newline would stay invisible — which
   *  is exactly what you need to see when a chip is silent or stuck. */
  private schedulePartialFlush() {
    clearTimeout(this.partialTimer);
    this.partialTimer = setTimeout(() => {
      if (this.rxBuf.length) this.emit("rx", `${this.rxBuf}  ⟨no newline yet⟩`);
    }, 800);
  }

  async serialClose() {
    clearTimeout(this.partialTimer);
    this.closing = true;
    // The catches are attached HERE, not in the loop: all three promises start
    // now, and one rejecting before its turn would otherwise surface as an
    // unhandled rejection.
    const stages: [string, Promise<unknown> | undefined][] = [
      ["reader.cancel", this.reader?.cancel().catch(() => {})],
      ["writer.close", this.writer?.close().catch(() => {})],
      ["read loop", this.readerTask?.catch(() => {})],
    ];
    for (const [name, work] of stages) {
      if ((await within(1500, work)) === "timeout")
        this.emit("err", `${name} did not finish in 1.5s — closing the port anyway`);
    }
    try {
      this.reader?.releaseLock();
    } catch { /* closing */ }
    try {
      this.writer?.releaseLock();
    } catch { /* closing */ }
    try {
      await this.port?.close();
    } catch (e) {
      // NOT silent: a close that failed leaves the port open, and the next
      // open — this run's or the next device's — fails with a message that
      // says nothing about why.
      this.emit("err", `port close failed: ${(e as Error).message}`);
    }
    this.reader = this.writer = null;
    this.readerTask = null;
    this.closing = false;
    this.emit("app", "monitor serial closed");
  }

  async write(text: string) {
    if (!this.writer) throw new Error("monitor serial not open");
    await this.writer.write(enc.encode(text));
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
    // Whatever this opens, it closes. Everything else in this class treats an
    // open reader as "a run is using the port": `noteDisconnect` refuses to
    // release a held port while one exists, and `identifyPort` opens the port
    // to learn its socket, which fails on a port that is already open. A probe
    // that stayed open therefore cost the station its socket on the next
    // replug (reported 2026-09-17). It is a question, not a session.
    const wasOpen = !!this.reader;
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
  async monitorReset(monitorBaud: number) {
    if (!this.port) throw new Error("no port");
    const profile = this.profile();
    if (profile.reenumerates_on_reset) {
      await this.port.setSignals({ dataTerminalReady: false, requestToSend: false });
      await sleep(100);
      await this.port.setSignals({ dataTerminalReady: false, requestToSend: true });
      await sleep(100);
      await this.port.setSignals({ dataTerminalReady: false, requestToSend: false });
      this.emit("app", "USB-Serial/JTAG reset sequence sent");
      await this.serialClose();
      await this.awaitReenumerate(20000);
      await this.serialOpen(monitorBaud);
    } else {
      await this.port.setSignals({ requestToSend: false });
      await sleep(500);
      await this.port.setSignals({ requestToSend: true });
      await sleep(500);
      await this.port.setSignals({ requestToSend: false });
      this.emit("app", "RTS reset pulse sent");
    }
  }

  async cleanup() {
    try {
      if (this.reader) await this.serialClose();
      if (this.transport) await this.transport.disconnect();
    } catch (e) {
      this.emit("err", `cleanup: ${(e as Error).message}`);
    }
    this.transport = null;
    this.loader = null;
  }
}
