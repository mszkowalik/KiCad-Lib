/** WebSocket client for one programming run.
 *
 *  The backend engine owns the scenario; this client executes its `action`
 *  messages on the Station (esptool phase), pipes `tx`/`rx` bytes during the
 *  dialog phase, answers `prompt`s (SIM PIN), and mirrors `state`/`done` into
 *  the bench UI. Every station log line is ALSO forwarded as {t:"log"} so the
 *  stored run log is complete.
 */
import { flasherWsUrl } from "../api";
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

export class RunClient {
  private ws: WebSocket | null = null;
  private spec: RunSpec | null = null;
  private done = false;

  constructor(
    readonly station: Station,
    readonly runId: number,
    readonly params: Record<string, string>,
    readonly events: RunUiEvents,
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
            client_info: {
              user_agent: navigator.userAgent,
              usb: this.station.portIds,
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
        default:
          throw new Error(`bench cannot execute op "${msg.op}"`);
      }
      this.send({ t: "result", id: msg.id, ok: true, info });
    } catch (e) {
      this.send({ t: "result", id: msg.id, ok: false, error: (e as Error).message });
    }
  }
}
