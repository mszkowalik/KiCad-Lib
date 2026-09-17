/** WebSocket client for one programming run.
 *
 *  The backend engine owns the scenario; this client executes its `action`
 *  messages on the Station (esptool phase), pipes `tx`/`rx` bytes during the
 *  dialog phase, answers `prompt`s (SIM PIN), and mirrors `state`/`done` into
 *  the bench UI. Every station log line is ALSO forwarded as {t:"log"} so the
 *  stored run log is complete.
 */
import { apiBaseUrl, flasherWsUrl, sameOriginBase } from "../api";
import { runMarkJob, runPrintJob } from "./benchAgent";
import { Station, type FlashImage, type LogDir } from "./station";

export interface RunSpec {
  deployment_name: string;
  deployment_version_no: number;
  draft: boolean;
  chip: string;
  transport_profile: string;
  monitor_baud: number;
  flash_config: Record<string, string> | null;
  images: FlashImage[];
  steps: { op: string; label: string }[];
}

export interface RunUiEvents {
  onSpec(spec: RunSpec): void;
  onState(state: { index: number; total: number; label: string; status: string }): void;
  onLog(dir: LogDir, text: string): void;
  onProgress(pct: number | null): void;
  /** What is about to be engraved, the moment the bench knows it — which is
   *  before the laser fires, not after the run ends. The marking bench shows it
   *  so the operator can check the part against the screen. */
  onMarked?(value: string): void;
  /** What went on the label, once the printer says it finished. */
  onPrinted?(value: string): void;
  /** Modal for a mid-run operator input (e.g. the SIM PIN). Resolving with
   *  "" tells the engine nothing was provided. */
  onPrompt(field: string, label: string, secret: boolean): Promise<string>;
  onDone(status: string, error: string | null, results: Record<string, unknown>): void;
}

interface ActionMsg {
  t: "action";
  id: number;
  op: string;
  args: Record<string, unknown>;
}

/** What the BENCH brings to a run, as opposed to what the version says.
 *
 *  Two of these are physical and one is a choice the operator made by pressing
 *  one button rather than the other. None of them belong in the procedure: the
 *  printer and the roll are what is on this desk, and `skipOps` is which of the
 *  two actions this press asked for. The engine refuses to skip anything but
 *  those actions, so a bench cannot quietly change what a unit was made under.
 */
export interface BenchSettings {
  printer?: string;
  roll?: string;
  skipOps?: string[];
}

export class RunClient {
  private ws: WebSocket | null = null;
  private spec: RunSpec | null = null;
  private done = false;

  constructor(
    readonly station: Station,
    readonly runId: number,
    readonly params: Record<string, string>,
    readonly events: RunUiEvents,
    readonly bench: BenchSettings = {},
  ) {}

  start(): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(flasherWsUrl(this.runId));
      this.ws = ws;

      this.station.onEvent = (dir, text) => {
        this.events.onLog(dir, text);
        // rx goes through onLine; everything else is duplicated to the record.
        if (dir !== "rx" && ws.readyState === WebSocket.OPEN)
          ws.send(JSON.stringify({ t: "log", dir, text }));
      };
      this.station.onLine = (line) => {
        this.events.onLog("rx", line);
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ t: "rx", data: line }));
      };
      this.station.onProgress = (pct) => this.events.onProgress(pct);

      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            t: "hello",
            params: this.params,
            skip_ops: this.bench.skipOps ?? [],
            client_info: {
              user_agent: navigator.userAgent,
              // The SOCKET, not USB ids: the agent names the port and the ids
              // never distinguished two identical dongles anyway.
              socket: this.station.socket,
              // Two addresses this browser is PROVABLY reaching the platform
              // by. The engine picks the first one a device on WiFi could use
              // too, which is how {base_url} resolves without configuration.
              api_base: apiBaseUrl(),
              page_base: sameOriginBase(),
            },
          }),
        );
      };
      ws.onmessage = (ev) => {
        void this.handle(JSON.parse(ev.data as string) as Record<string, unknown>);
      };
      ws.onerror = () => {
        if (!this.done) reject(new Error("WebSocket error — is the API up?"));
      };
      ws.onclose = () => {
        if (!this.done) {
          this.done = true;
          this.events.onDone("aborted", "connection to the engine lost", {});
        }
        void this.station.cleanup();
        resolve();
      };
    });
  }

  abort() {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ t: "abort" }));
  }

  private send(msg: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private async handle(msg: Record<string, unknown>) {
    switch (msg.t) {
      case "run": {
        this.spec = msg.spec as RunSpec;
        this.station.profileKey = this.spec.transport_profile;
        this.events.onSpec(this.spec);
        return;
      }
      case "action":
        await this.runAction(msg as unknown as ActionMsg);
        return;
      case "tx": {
        try {
          const data = String(msg.data ?? "");
          this.events.onLog("tx", data.replace(/\n$/, ""));
          await this.station.write(data);
        } catch (e) {
          this.events.onLog("err", `tx failed: ${(e as Error).message}`);
        }
        return;
      }
      case "state":
        this.events.onState(msg as unknown as { index: number; total: number; label: string; status: string });
        return;
      case "prompt": {
        const value = await this.events.onPrompt(
          String(msg.field ?? ""),
          String(msg.label ?? "Input needed"),
          Boolean(msg.secret),
        );
        this.send({ t: "prompt_result", id: msg.id, value });
        return;
      }
      case "done": {
        this.done = true;
        this.events.onDone(
          String(msg.status ?? "fail"),
          (msg.error as string | null) ?? null,
          (msg.results as Record<string, unknown>) ?? {},
        );
        return;
      }
    }
  }

  private async runAction(msg: ActionMsg) {
    const st = this.station;
    const spec = this.spec;
    try {
      let info: Record<string, unknown> = {};
      switch (msg.op) {
        case "esp_connect":
          info = await st.espOpen(spec?.chip ?? "");
          break;
        case "erase":
          await st.espErase();
          break;
        case "flash":
          await st.espFlash(
            (msg.args.images as FlashImage[]) ?? [],
            (msg.args.flash_config as Record<string, string>) ?? {},
            msg.args.verify_md5 !== false,
          );
          break;
        case "esp_reset":
          await st.espReset();
          break;
        case "await_reenumerate":
          await st.awaitReenumerate(Number(msg.args.timeout ?? 25) * 1000);
          break;
        case "serial_open":
          await st.serialOpen(Number(msg.args.baud ?? spec?.monitor_baud ?? 115200));
          break;
        case "serial_close":
          await st.serialClose();
          break;
        case "reset":
          await st.monitorReset(spec?.monitor_baud ?? 115200);
          break;
        case "mark_laser":
          info = await this.markLaser(msg.args);
          break;
        case "print_label":
          info = await this.printLabel(msg.args);
          break;
        default:
          throw new Error(`bench cannot execute op "${msg.op}"`);
      }
      this.send({ t: "result", id: msg.id, ok: true, info });
    } catch (e) {
      this.send({ t: "result", id: msg.id, ok: false, error: (e as Error).message });
    }
  }

  /** The other op that leaves this machine, and the shorter of the two.
   *
   *  Nothing is fetched and nothing is patched: the agent lays the label out,
   *  because the geometry lives in the printer's PPD beside the printer. The
   *  queue and the roll come from the BENCH, not from the step, and what the
   *  agent reports back is what the run records — so the history says which
   *  roll a unit's label was really printed on.
   */
  private async printLabel(args: Record<string, unknown>): Promise<Record<string, unknown>> {
    const roll = this.bench.roll || String(args.size ?? "");
    const out = await runPrintJob(
      {
        value: String(args.value ?? ""),
        printer: this.bench.printer,
        roll,
        dots: Number(args.dots ?? 3),
        rotate: args.rotate !== false,
        copies: Number(args.copies ?? 1),
        jobTimeoutS: Number(args.job_timeout ?? 120),
      },
      (dir, text) => this.events.onLog((dir as LogDir) ?? "app", text),
    );
    if (out.status !== "pass") throw new Error(out.error || "the label did not print");
    this.events.onPrinted?.(String(args.value ?? ""));
    return {
      printer: this.bench.printer ?? "",
      roll,
      job_seconds: out.job_seconds ?? null,
      cups_job: out.cups_job ?? null,
    };
  }

  /** The one op the bench does not execute itself.
   *
   *  The engine names a template this version pins and the text to put in it.
   *  The page fetches the artwork, patches the one text shape, and relays the
   *  finished job to the bench agent — which is the only thing here that can
   *  talk to LightBurn. Every line the agent reports goes into the run log, so
   *  a mark is as readable afterwards as a flash is.
   */
  private async markLaser(args: Record<string, unknown>): Promise<Record<string, unknown>> {
    this.events.onMarked?.(String(args.value ?? ""));
    const out = await runMarkJob(
      apiBaseUrl(),
      {
        fileVersionId: Number(args.file_version_id),
        filename: String(args.filename ?? ""),
        value: String(args.value ?? ""),
        placeholder: args.placeholder ? String(args.placeholder) : undefined,
        device: args.device ? String(args.device) : undefined,
        start: args.start !== false,
        jobTimeoutS: Number(args.job_timeout ?? 300),
      },
      (dir, text) => this.events.onLog((dir as LogDir) ?? "app", text),
    );
    if (out.status !== "pass") throw new Error(out.error || "the mark failed");
    return { job_seconds: out.job_seconds ?? null, job_file: out.job_file ?? null };
  }
}
