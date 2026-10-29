/** The page's half of the bench agent.
 *
 *  The agent is the part of the bench that has to run ON THE MACHINE, because a
 *  browser cannot do it: send a UDP datagram to LightBurn, and see the real
 *  `/dev/cu.*` names. It is one standard-library Python file the operator
 *  downloads from the bench and double-clicks
 *  (`api/app/services/bench_agent/agent.py`).
 *
 *  For marking, the page owns the artwork: it fetches the `.lbrn2` the deployment version
 *  pins, replaces the placeholder text with the device's own identity, and
 *  hands the FINISHED job to the bench agent. The agent owns only LightBurn,
 *  because a browser cannot send a UDP datagram and that is the entire reason
 *  it exists (`api/app/services/bench_agent/agent.py`).
 *
 *  Three things about the connection are load-bearing:
 *
 *  1. **It is plain HTTP, not a WebSocket, so the agent needs no install.**
 *     Every import in `agent.py` is standard library, which is what lets any
 *     Python already on the bench run one downloaded file. The cost is that a
 *     mark's log is POLLED rather than pushed, which for a job measured in
 *     seconds is not a cost at all.
 *  2. **Chrome blocks this by default.** A page on a public origin reaching
 *     127.0.0.1 trips Local Network Access, which fails with
 *     `ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS` rather than a timeout.
 *     Chrome 141+ prompts the operator once; a bench that must never prompt
 *     gets `LoopbackNetworkAccessAllowedForUrls` from the bench profile. The
 *     error text below says so, because the failure otherwise reads as "the
 *     agent is not running" when it is.
 *  3. **The agent checks our Origin**, so anything that reaches it has been
 *     allowed deliberately. Nothing here sends a token, and nothing should:
 *     a token in a page is not a secret.
 */

import { setFileText } from "./fileCache";

const AGENT_URL = "http://127.0.0.1:19842";
/** What this page needs the agent to speak. 3 added the printer routes.
 *
 *  An older agent answers 404 on them, which reads as "the printer is broken"
 *  rather than "this machine is running last month's agent" — so the page asks
 *  once, at hello, and says which it is. The agent is downloaded, not deployed,
 *  so a bench really can be behind. */
export const NEEDS_PROTOCOL = 3;

/** Can this agent PROGRAM? Not a version test on purpose.
 *
 *  `/esp` and the vendored esptool arrived in decision 0023 and the protocol
 *  number was left at 3, so a pre-0023 agent reports exactly what a current one
 *  does — the bench took a job against one and failed with the agent's own 404,
 *  `no such path`, after a device was already in the socket (2026-09-17).
 *  Raising the number would have been the tidy answer and the wrong one: it
 *  would also condemn every agent that programs perfectly well, for a download
 *  nobody needs. `/hello` already reports the esptool it carries, and that IS
 *  the capability — so ask the question that matters instead of a proxy for it.
 *
 *  `PROTOCOL_VERSION` is bumped to 4 in `agent.py` all the same, so the next
 *  download stops lying about what it is. */
export function canProgram(hello: { esptool?: string | null }): boolean {
  return Boolean(hello.esptool);
}

/** What `/hello` says this agent can do. Each flag is a CAPABILITY, for the
 *  reason `canProgram` gives: an agent from before it simply does not send it. */
export interface AgentHello {
  agent: string;
  protocol: number;
  lightburn_host: string;
  esptool?: string | null;
  /** One console and one esptool job PER PORT (decision 0099). Without it the
   *  agent has one of each for the whole machine, and a second station's
   *  console closes the first one's (runs 8964 and 8966). */
  per_port?: boolean;
  /** `POST /esp/cancel` exists: Abort and "Stop waiting" stop esptool. */
  esp_cancel?: boolean;
  /** Flash images may be named by SHA-256, from the agent's own cache. */
  image_cache?: boolean;
}

/** Can several stations run at the same time on this agent? */
export function canRunStationsTogether(hello: AgentHello): boolean {
  return Boolean(hello.per_port);
}
/** How often a running job's log is collected. Fast enough that the operator
 *  sees the laser start, slow enough to be free. */
const POLL_MS = 400;

export interface MarkLog {
  dir: string;
  text: string;
}

export interface MarkResult {
  status: "pass" | "fail";
  error?: string;
  job_seconds?: number;
  job_file?: string;
}

/** The shapes that can carry the value, and the attribute that holds it.
 *  LightBurn stores no geometry for a `BarCode` — only its `Content` — and
 *  draws the code when the file loads, so the QR beside the serial on the
 *  Dongle V3 artwork is patched the same way as the text (2026-10-14). */
const VALUE_ATTR: Record<string, string> = { Text: "Str", BarCode: "Content" };

function placeholderShapes(doc: Document, placeholder: string): [Element, string][] {
  const out: [Element, string][] = [];
  for (const shape of Array.from(doc.querySelectorAll("Shape"))) {
    const attr = VALUE_ATTR[shape.getAttribute("Type") ?? ""];
    if (attr && shape.getAttribute(attr) === placeholder) out.push([shape, attr]);
  }
  return out;
}

/** Put `value` into every shape that carries the placeholder, returning the
 *  new XML.
 *
 *  This is `mark.py`'s `patch_template` in the browser: a `Text` shape's
 *  `Str` and a `BarCode` shape's `Content`, nothing else. Everything else in
 *  the file — the layers, the speeds, the correction LightBurn applies — is
 *  left exactly as the artwork author left it, which is the whole point of
 *  patching rather than generating.
 *
 *  The first placeholder that any shape carries wins, and EVERY shape that
 *  carries it is patched. A placeholder still in the file afterwards is
 *  refused: a QR left saying `123456789011` reads as a working mark and
 *  identifies nothing.
 */
/** `placeholders` is stated by the caller and never guessed here. The engine
 *  sends the step's own, or the platform's defaults
 *  (`engine.DEFAULT_MARK_PLACEHOLDERS`) — a constant in a browser bundle must
 *  not decide what is engraved on a part. */
export function patchTemplate(xml: string, value: string, placeholders: string[]): string {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  if (doc.querySelector("parsererror")) throw new Error("the template is not valid XML");
  const wanted = placeholders.filter(Boolean);
  if (!wanted.length) throw new Error("no placeholder named for this template");
  const hit = wanted.find((p) => placeholderShapes(doc, p).length);
  if (hit === undefined) {
    throw new Error(
      `the template has no text or barcode saying ${wanted.join(" or ")} — name the placeholder on the step`,
    );
  }
  for (const [shape, attr] of placeholderShapes(doc, hit)) shape.setAttribute(attr, value);
  const left = wanted.filter((p) => p !== value && placeholderShapes(doc, p).length);
  if (left.length) {
    throw new Error(
      `the template still says ${left.join(" and ")} after ${hit} was replaced — use one placeholder for every text and barcode`,
    );
  }
  return new XMLSerializer().serializeToString(doc);
}

function toBase64(s: string): string {
  // The .lbrn2 carries a UTF-8 thumbnail blob and accented layer names, so the
  // string has to become bytes before it becomes base64.
  const bytes = new TextEncoder().encode(s);
  let out = "";
  for (const b of bytes) out += String.fromCharCode(b);
  return btoa(out);
}

export interface AgentPort {
  /** The real node, e.g. "/dev/cu.usbserial-110". On macOS the name comes from
   *  the USB LOCATION, so it identifies the SOCKET, not the device. */
  device: string;
  /** The process holding it open, from lsof, or "" when free. */
  held_by: string;
  /** The USB serial number, "" when the device has none. An ESP32-C6 reports
   *  its MAC here, so a NEW unit can be told from the same unit coming back
   *  after its own reset; a CH340 reports none. An older agent omits it. */
  serial_number?: string;
}

/** Every USB serial node on the bench machine, and who holds each.
 *
 *  This is what Web Serial refuses to tell a page — it exposes a vendor and
 *  product id and nothing else, so three identical CH340s are indistinguishable
 *  and a station could never be tied to a socket. See
 *  docs/reference/bench-serial-ports.md.
 */
export async function listSerialPorts(): Promise<AgentPort[]> {
  const r = await new MarkAgent().call("/serial-ports");
  return (r.ports ?? []) as AgentPort[];
}

/** How often the stations learn what is plugged in. */
const PORT_POLL_MS = 2000;
const portWatchers = new Set<(ports: AgentPort[] | null) => void>();
let portTimer = 0;
let lastPorts: AgentPort[] | null = null;
/** Which poll loop is current. A loop whose tick was in flight when the last
 *  station left must not reschedule beside the one the next station starts. */
let portLoop = 0;

/** The agent's port list, ONE poll for the whole page.
 *
 *  Every station used to poll on its own, and each answer ran lsof once per
 *  node, so four stations cost twenty lsof runs every two seconds. Now the
 *  page asks once and every station hears the same answer — which also means
 *  two stations never disagree about what is plugged in. `null` = the agent
 *  is not answering. Returns the unsubscribe.
 */
export function watchSerialPorts(onPorts: (ports: AgentPort[] | null) => void): () => void {
  portWatchers.add(onPorts);
  if (lastPorts) onPorts(lastPorts);
  if (portWatchers.size === 1) {
    const loop = ++portLoop;
    const tick = async () => {
      let got: AgentPort[] | null = null;
      try {
        got = await listSerialPorts();
      } catch {
        got = null; // the agent is not running
      }
      if (loop !== portLoop) return; // stopped while this tick was out
      lastPorts = got;
      for (const w of portWatchers) w(got);
      if (portWatchers.size) portTimer = window.setTimeout(tick, PORT_POLL_MS);
    };
    void tick();
  }
  return () => {
    portWatchers.delete(onPorts);
    if (!portWatchers.size) {
      window.clearTimeout(portTimer);
      portLoop++;
      lastPorts = null;
    }
  };
}

/** What `/health` says. `laserUsb` is whether the laser CONTROLLER is on the
 *  bench machine's USB bus — the one thing LightBurn cannot report, since its
 *  STATUS answers OK on a profile that shows "Disconnected". null = the agent
 *  cannot tell (not macOS, or an older agent). */
export interface AgentHealth {
  responsive: boolean;
  busy: boolean | null;
  laserUsb: { present: boolean; name: string; ids: string } | null;
}

export interface MarkJob {
  fileSetId: number;
  filename: string;
  /** The LightBurn DEVICE PROFILE to mark under, as LightBurn names it — a
   *  profile carries one source's calibration; the artwork's layers pick the
   *  source. Empty = leave whatever LightBurn has selected. Only the profile
   *  LightBurn started with can connect, so the agent refuses to switch. */
  device?: string;
  /** what goes on the part */
  value: string;
  /** empty = the strings the CE templates already use */
  placeholders: string[];
  start: boolean;
  jobTimeoutS: number;
}

/** Fetch the artwork, patch it, mark. The ONE implementation.
 *
 *  Both callers arrive here: a marking RUN, where the engine named the template
 *  and the bench read the value off the device, and the MANUAL mark, where the
 *  operator typed the value for a unit that will not talk. The difference
 *  between them is where the string came from, and that is all it should ever
 *  be — two copies of this would drift the moment one of them learned
 *  something.
 */
export async function runMarkJob(
  apiBase: string,
  job: MarkJob,
  onLog: (dir: string, text: string) => void,
): Promise<MarkResult> {
  // Kept in the browser by set and name: a set never changes (decision 0029),
  // and the bench marks the same drawing all day.
  onLog("app", `artwork ${job.filename}`);
  const xml = await setFileText(job.fileSetId, job.filename, apiBase);
  const patched = patchTemplate(xml, job.value, job.placeholders);
  onLog("app", `patched ${job.filename} with ${job.value}`);

  const agent = new MarkAgent();
  try {
    const health = await agent.health();
    if (!health.responsive) {
      throw new Error(
        "LightBurn is not answering. It is not running, or a dialog is open on the bench machine.",
      );
    }
    return await agent.mark(
      { name: job.value, lbrn2: patched, start: job.start, jobTimeoutS: job.jobTimeoutS,
        device: job.device },
      (l) => onLog(l.dir, l.text),
    );
  } finally {
    agent.close();
  }
}

export interface AgentPrinter {
  queue: string;
  idle: boolean;
  /** Its PPD comes from DYMO, so it is a label printer rather than a page one. */
  label_printer: boolean;
  default: boolean;
  /** Empty when nothing is wrong. `com.dymo.slot-status-error` is the one this
   *  bench raises: no roll, lid open, or labels that are not DYMO Authentic. */
  reasons: string;
  ok: boolean;
}

export interface AgentRoll {
  /** The PPD's own name for it, e.g. "w72h154" — what `lp -o PageSize=` takes. */
  size: string;
  name: string;
  label_mm: [number, number];
  printable_mm: [number, number];
}

export interface PrintResult {
  status: "pass" | "fail";
  error?: string;
  printed?: string;
  job_seconds?: number;
  cups_job?: string;
}

export interface PrintJob {
  /** What goes on the label. */
  value: string;
  /** The queue, and the roll in it. Both are BENCH settings: the printer is
   *  physical and the procedure is not, and the printer cannot say what roll
   *  is loaded — CUPS reports no media-ready at all (measured 2026-09-17). */
  printer?: string;
  roll?: string;
  dots?: number;
  rotate?: boolean;
  copies?: number;
  jobTimeoutS?: number;
}

/** Every print queue on the bench machine, and the rolls one of them offers.
 *
 *  The rolls come from that printer's own PPD. Listing them here would mean a
 *  second copy of the printer's statement about itself, and the wrong one
 *  prints a barcode scaled to fit.
 */
export async function listPrinters(
  forPrinter?: string,
): Promise<{ printers: AgentPrinter[]; rolls: AgentRoll[]; defaultRoll: string }> {
  const agent = new MarkAgent();
  const q = forPrinter ? `?printer=${encodeURIComponent(forPrinter)}` : "";
  const r = await agent.call(`/printers${q}`);
  const printers = (r.printers ?? []) as AgentPrinter[];
  let rolls = (r.rolls ?? []) as AgentRoll[];
  // The agent lists rolls only for a NAMED queue. Asked for none, ask again
  // for the label printer, or the bench's roll picker offers nothing but the
  // fallback roll (found 2026-10-29, when the 57 x 32 mm roll arrived).
  const label = printers.find((p) => p.label_printer && p.default)
    ?? printers.find((p) => p.label_printer);
  if (!forPrinter && !rolls.length && label) {
    const again = await agent.call(`/printers?printer=${encodeURIComponent(label.queue)}`);
    rolls = (again.rolls ?? []) as AgentRoll[];
  }
  return { printers, rolls, defaultRoll: String(r.default_roll ?? "") };
}

/** Print one label. The ONE implementation, for the same reason `runMarkJob`
 *  is: a run and a button press differ only in where the string came from.
 *
 *  Unlike a mark, nothing is fetched and nothing is patched here. The agent
 *  lays the label out, because the geometry lives in the printer's PPD on that
 *  machine.
 */
export async function runPrintJob(
  job: PrintJob,
  onLog: (dir: string, text: string) => void,
): Promise<PrintResult> {
  const agent = new MarkAgent();
  try {
    return await agent.print(job, (l) => onLog(l.dir, l.text));
  } finally {
    agent.close();
  }
}

export class MarkAgent {
  /** One call. A network failure here is almost never "the server said no" —
   *  it is the agent being absent or Chrome refusing the loopback — so the
   *  message names both rather than surfacing "Failed to fetch". */
  async call(
    path: string,
    init?: RequestInit,
    timeoutMs = 10000,
  ): Promise<Record<string, unknown>> {
    const { ok, status, body } = await this.request(path, init, timeoutMs);
    if (!ok) {
      throw new Error(String(body.error ?? `the bench agent answered HTTP ${status}`));
    }
    return body;
  }

  /** `call` without the throw: the answer whatever its status, for a refusal
   *  that carries something to act on (`missing` images). */
  async request(
    path: string,
    init?: RequestInit,
    timeoutMs = 10000,
  ): Promise<{ ok: boolean; status: number; body: Record<string, unknown> }> {
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), timeoutMs);
    let res: Response;
    try {
      res = await fetch(AGENT_URL + path, { ...init, signal: ac.signal });
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        throw new Error(`the bench agent did not answer within ${timeoutMs / 1000}s`);
      }
      throw new Error(
        "cannot reach the bench agent on this machine. Either it is not running — " +
          "download it below and double-click 7Sigma Agent — or Chrome blocked the " +
          "connection to 127.0.0.1, which it asks about once.",
      );
    } finally {
      clearTimeout(timer);
    }
    const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    return { ok: res.ok, status: res.status, body };
  }

  // Nothing to close: each call is its own request. Kept so callers can go on
  // using the agent the same way whatever it speaks underneath.
  close() {}

  async hello(): Promise<AgentHello> {
    return (await this.call("/hello")) as unknown as AgentHello;
  }

  /** PING and STATUS. `responsive: false` means LightBurn is not running, or a
   *  modal dialog has frozen its interface — the two look identical over UDP. */
  async health(): Promise<AgentHealth> {
    const r = await this.call("/health");
    const usb = (r.laser_usb ?? null) as { present?: boolean | null; name?: string; ids?: string } | null;
    return {
      responsive: Boolean(r.responsive),
      busy: (r.busy ?? null) as boolean | null,
      // An agent from before this field existed answers without it: unknown, not absent.
      laserUsb: usb && usb.present !== undefined && usb.present !== null
        ? { present: Boolean(usb.present), name: String(usb.name ?? ""), ids: String(usb.ids ?? "") }
        : null,
    };
  }

  async mark(
    job: { name: string; lbrn2: string; start: boolean; jobTimeoutS: number; device?: string },
    onLog?: (l: MarkLog) => void,
  ): Promise<MarkResult> {
    const started = await this.call("/mark", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: job.name,
        lbrn2: toBase64(job.lbrn2),
        start: job.start,
        job_timeout: job.jobTimeoutS,
        device: job.device ?? "",
      }),
    });
    const r = await this.watch(Number(started.job), job.jobTimeoutS, "the mark", onLog);
    return {
      status: r.status,
      error: r.error,
      job_seconds: typeof r.job_seconds === "number" ? r.job_seconds : undefined,
      job_file: r.job_file ? String(r.job_file) : undefined,
    };
  }

  /** One ESP operation on the agent's own esptool (decision 0023): connect,
   *  erase, flash or reset, on a port named by its node. The agent walks the
   *  same connect ladder the tab did, and its log comes back line by line. */
  async esp(
    body: { op: string; port: string } & Record<string, unknown>,
    onLog?: (l: MarkLog) => void,
    opts: {
      /** The agent's job id, the moment it exists, so the station can cancel it. */
      onJob?: (id: number) => void;
      /** The agent lacks these images (by SHA-256): return the request's
       *  images again, with `data` on those. Called at most once. */
      supplyImages?: (missing: string[]) => Promise<Record<string, unknown>[]>;
    } = {},
  ): Promise<{
    status: "pass" | "fail"; error?: string; info?: Record<string, unknown>; cancelled?: boolean;
  }> {
    const timeoutS = body.op === "flash" ? 900 : body.op === "erase" ? 240 : 90;
    // Ask WHO is answering before handing it a device. An agent from before
    // decision 0023 has no `/esp` at all and returns its own 404 — the run then
    // failed with "no such path", which names nothing an operator can act on
    // (bench, 2026-09-17). The banner on the page says the same thing, but the
    // banner can be scrolled off and this cannot.
    const hello = await this.hello();
    if (!canProgram(hello)) {
      throw new Error(
        "the bench agent on this machine is too old to program — it carries no esptool. "
        + "Download it again, replace the copy in Applications, and restart it",
      );
    }
    const post = (b: Record<string, unknown>) => this.request("/esp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }, 60000);
    let started = await post(body);
    const missing = started.body.missing;
    if (!started.ok && Array.isArray(missing) && opts.supplyImages) {
      // The agent keeps images by SHA-256 (decision 0099). It said which ones
      // it lacks; send those bytes once and ask again.
      started = await post({ ...body, images: await opts.supplyImages(missing.map(String)) });
    }
    if (!started.ok || started.body.error) {
      throw new Error(String(started.body.error ?? `the bench agent answered HTTP ${started.status}`));
    }
    const id = Number(started.body.job);
    opts.onJob?.(id);
    const r = await this.watch(id, timeoutS, `${body.op} on the agent`, onLog);
    return {
      status: r.status,
      error: r.error,
      info: (r.info ?? undefined) as Record<string, unknown> | undefined,
      cancelled: Boolean(r.cancelled),
    };
  }

  /** Stop an esptool job: Abort, Abort during Erase, "Stop waiting" for BOOT.
   *  The agent answers once the job has ended. An agent from before
   *  `esp_cancel` answers 404, and there is then nothing this page can do —
   *  the job runs to its end, which is what Abort always did. */
  async cancelEsp(target: { job?: number; port?: string }): Promise<boolean> {
    const r = await this.request("/esp/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(target),
    });
    return r.ok;
  }

  /** The device console, held open by the AGENT (decision 0023).
   *
   *  The browser never touches the serial port: the agent opens it, reads it in
   *  a thread, and this polls for the lines. That is what lets a bench run with
   *  no Web Serial grant, no port picker and no Chrome policy at all.
   */
  async monitorOpen(port: string, baud: number, signals: object | null): Promise<void> {
    const r = await this.call("/monitor/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port, baud, signals }),
    });
    if (r.error) throw new Error(String(r.error));
  }

  /** @param waitS hold the request open until a line appears, or this expires.
   *    Long polling, so a device reply reaches the engine in a round trip
   *    rather than at the next tick of a timer. */
  async monitorLines(
    port: string,
    since: number,
    waitS = 0,
  ): Promise<{ open: boolean; seen: number; lines: string[]; error?: string }> {
    // The agent holds this request for `waitS`, so the client deadline must sit
    // ABOVE it. At the default 10 s both sides expired together and any quiet
    // device produced "the bench agent did not answer within 10s" on a poll
    // that was working correctly (run 6442, 2026-09-17).
    const r = await this.call(
      `/monitor?port=${encodeURIComponent(port)}&since=${since}&wait=${waitS}`,
      undefined,
      Math.max(10000, waitS * 1000 + 5000),
    );
    return {
      open: Boolean(r.open),
      seen: Number(r.seen ?? since),
      lines: ((r.lines ?? []) as { text?: string }[]).map((l) => String(l.text ?? "")),
      // The console reader stopped: the device left the bus. An older agent
      // never sends it, and its runs wait out each step as before.
      error: r.error ? String(r.error) : undefined,
    };
  }

  /** Every console call names its PORT (decision 0099): the agent keeps one
   *  console per port, and a call for a port with no open console fails
   *  rather than reaching another station's unit. An older agent ignores the
   *  field and uses its one console, which is right for one station. */
  async monitorWrite(port: string, text: string): Promise<void> {
    const r = await this.call("/monitor/write", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port, text }),
    });
    if (r.error) throw new Error(String(r.error));
  }

  async monitorReset(port: string): Promise<void> {
    const r = await this.call("/monitor/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port }),
    });
    if (r.error) throw new Error(String(r.error));
  }

  async monitorClose(port: string): Promise<void> {
    await this.call("/monitor/close", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port }),
    });
  }

  async print(job: PrintJob, onLog?: (l: MarkLog) => void): Promise<PrintResult> {
    const timeout = job.jobTimeoutS ?? 120;
    const started = await this.call("/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        value: job.value,
        printer: job.printer ?? "",
        size: job.roll ?? "",
        dots: job.dots ?? 3,
        rotate: job.rotate !== false,
        copies: job.copies ?? 1,
        job_timeout: timeout,
      }),
    });
    const r = await this.watch(Number(started.job), timeout, "the label", onLog);
    return {
      status: r.status,
      error: r.error,
      printed: r.printed ? String(r.printed) : undefined,
      job_seconds: typeof r.job_seconds === "number" ? r.job_seconds : undefined,
      cups_job: r.cups_job ? String(r.cups_job) : undefined,
    };
  }

  /** Follow one job to its end, whichever machine it is on.
   *
   *  The laser and the printer report through the same job log deliberately:
   *  the operator reads one place, and a run record carries both the same way.
   */
  private async watch(
    id: number,
    timeoutS: number,
    what: string,
    onLog?: (l: MarkLog) => void,
  ): Promise<Record<string, unknown> & { status: "pass" | "fail"; error?: string }> {
    // The deadline is the agent's own job timeout plus slack: past that the
    // agent has given up too, so waiting longer only hides the answer.
    const deadline = Date.now() + (timeoutS + 30) * 1000;
    let seen = 0;
    for (;;) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      const r = await this.call(`/job/${id}?since=${seen}`);
      const lines = (r.lines ?? []) as MarkLog[];
      seen += lines.length;
      for (const l of lines) onLog?.({ dir: String(l.dir ?? "app"), text: String(l.text ?? "") });
      if (r.done) {
        return {
          ...r,
          status: r.status === "pass" ? "pass" : "fail",
          error: r.error ? String(r.error) : undefined,
        };
      }
      if (Date.now() > deadline) {
        return { status: "fail", error: `${what} did not finish in time` };
      }
    }
  }
}
