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
/** How often a running job's log is collected. Fast enough that the operator
 *  sees the laser start, slow enough to be free. */
const POLL_MS = 400;

/** The placeholder strings the CE templates have always used. First hit wins,
 *  same order as the old tool, so an unchanged drawing needs no step argument. */
const DEFAULT_PLACEHOLDERS = ["123456789011", "123456"];

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

/** Replace the placeholder text shape with `value`, returning the new XML.
 *
 *  This is `mark.py`'s `patch_template` in the browser: one Text shape, one
 *  attribute. Everything else in the file — the layers, the speeds, the
 *  correction LightBurn applies — is left exactly as the artwork author left
 *  it, which is the whole point of patching rather than generating.
 */
export function patchTemplate(xml: string, value: string, placeholder?: string): string {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  if (doc.querySelector("parsererror")) throw new Error("the template is not valid XML");
  const wanted = placeholder ? [placeholder] : DEFAULT_PLACEHOLDERS;
  for (const p of wanted) {
    for (const shape of Array.from(doc.querySelectorAll('Shape[Type="Text"]'))) {
      if (shape.getAttribute("Str") === p) {
        shape.setAttribute("Str", value);
        return new XMLSerializer().serializeToString(doc);
      }
    }
  }
  throw new Error(
    `the template has no text shape saying ${wanted.join(" or ")} — name the placeholder on the step`,
  );
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
  fileVersionId: number;
  filename: string;
  /** The LightBurn DEVICE PROFILE to mark under, as LightBurn names it — a
   *  profile carries one source's calibration; the artwork's layers pick the
   *  source. Empty = leave whatever LightBurn has selected. Only the profile
   *  LightBurn started with can connect, so the agent refuses to switch. */
  device?: string;
  /** what goes on the part */
  value: string;
  /** empty = the strings the CE templates already use */
  placeholder?: string;
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
  const url = `${apiBase}/api/flasher/files/${job.fileVersionId}/${encodeURIComponent(job.filename)}`;
  onLog("app", `fetching ${job.filename}`);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`could not fetch ${job.filename}: HTTP ${res.status}`);
  const patched = patchTemplate(await res.text(), job.value, job.placeholder);
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
  const q = forPrinter ? `?printer=${encodeURIComponent(forPrinter)}` : "";
  const r = await new MarkAgent().call(`/printers${q}`);
  return {
    printers: (r.printers ?? []) as AgentPrinter[],
    rolls: (r.rolls ?? []) as AgentRoll[],
    defaultRoll: String(r.default_roll ?? ""),
  };
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
    if (!res.ok) {
      throw new Error(String(body.error ?? `the bench agent answered HTTP ${res.status}`));
    }
    return body;
  }

  // Nothing to close: each call is its own request. Kept so callers can go on
  // using the agent the same way whatever it speaks underneath.
  close() {}

  async hello(): Promise<{
    agent: string; protocol: number; lightburn_host: string; esptool?: string | null;
  }> {
    return (await this.call("/hello")) as unknown as {
      agent: string;
      protocol: number;
      lightburn_host: string;
    };
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
  ): Promise<{ status: "pass" | "fail"; error?: string; info?: Record<string, unknown> }> {
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
    const started = await this.call("/esp", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (started.error) throw new Error(String(started.error));
    const r = await this.watch(Number(started.job), timeoutS, `${body.op} on the agent`, onLog);
    return {
      status: r.status,
      error: r.error,
      info: (r.info ?? undefined) as Record<string, unknown> | undefined,
    };
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
    since: number,
    waitS = 0,
  ): Promise<{ open: boolean; seen: number; lines: string[] }> {
    const r = await this.call(`/monitor?since=${since}&wait=${waitS}`);
    return {
      open: Boolean(r.open),
      seen: Number(r.seen ?? since),
      lines: ((r.lines ?? []) as { text?: string }[]).map((l) => String(l.text ?? "")),
    };
  }

  async monitorWrite(text: string): Promise<void> {
    const r = await this.call("/monitor/write", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (r.error) throw new Error(String(r.error));
  }

  async monitorReset(): Promise<void> {
    const r = await this.call("/monitor/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (r.error) throw new Error(String(r.error));
  }

  async monitorClose(): Promise<void> {
    await this.call("/monitor/close", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
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
