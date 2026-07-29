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

export class Station {
  port: SerialPort | null = null;
  portIds: Partial<SerialPortInfo> = {};
  profileKey = "uart_bridge";
  progress: number | null = null;
  lost = false;

  onEvent: (dir: LogDir, text: string) => void = () => {};
  onLine: (line: string) => void = () => {};
  onProgress: (pct: number | null) => void = () => {};

  private transport: Transport | null = null;
  private loader: ESPLoader | null = null;
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

  get portLabel(): string {
    if (!this.port) return "—";
    const i = this.port.getInfo();
    if (!i.usbVendorId) return "serial port";
    const ids = `${i.usbVendorId.toString(16).padStart(4, "0")}:${(i.usbProductId ?? 0)
      .toString(16)
      .padStart(4, "0")}`;
    return `USB ${ids} · ${TRANSPORT_PROFILES[autoProfile(this.port)].label}`;
  }

  profile(profileKey?: string): TransportProfile {
    const key = profileKey || this.profileKey || autoProfile(this.port);
    return TRANSPORT_PROFILES[key] ?? TRANSPORT_PROFILES.uart_bridge;
  }

  async requestPort() {
    this.port = await navigator.serial.requestPort();
    this.portIds = this.port.getInfo();
    this.emit("app", `port granted: ${this.portLabel}`);
  }

  attachPort(port: SerialPort) {
    this.port = port;
    this.portIds = port.getInfo();
    this.emit("app", `port attached (previously granted): ${this.portLabel}`);
  }

  // ---------------------------------------------------------------- esptool

  async espOpen(chipExpect: string): Promise<{ chip: string; mac: string }> {
    if (!this.port) throw new Error("no port");
    const profile = this.profile();
    const terminal = {
      clean: () => {},
      writeLine: (d: string) => this.emit("esptool", d),
      write: (d: string) => {
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
      baudrate: profile.flash_baud,
      terminal,
      debugLogging: false,
    });
    this.emit(
      "app",
      `transport profile: ${profile.label} (before=${profile.before}, flash baud=${profile.flash_baud})`,
    );
    const chip = await this.loader.main(profile.before);
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
    await this.loader.writeFlash({
      fileArray,
      flashMode: (flashConfig.mode ?? "keep") as FlashOpts["flashMode"],
      flashFreq: (flashConfig.freq ?? "keep") as FlashOpts["flashFreq"],
      flashSize: (flashConfig.size ?? "keep") as FlashOpts["flashSize"],
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
    return true;
  }

  noteConnect(port: SerialPort): boolean {
    if (!this.sameDevice(port)) return false;
    this.port = port;
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
      const candidate: SerialPort = ports.find((p) => this.sameDevice(p)) ?? this.port;
      try {
        await candidate.open({ baudRate: 115200 });
        await candidate.close();
        this.port = candidate;
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
    for (let attempt = 1; ; attempt++) {
      try {
        await this.port.open({ baudRate: baud, bufferSize: 8192 });
        break;
      } catch (e) {
        if (attempt >= 10)
          throw new Error(`could not open port at ${baud}: ${(e as Error).message}`);
        this.emit("app", `open attempt ${attempt} failed (${(e as Error).message}) — retrying`);
        await sleep(400);
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
    try {
      await this.reader?.cancel();
    } catch { /* closing */ }
    try {
      this.reader?.releaseLock();
    } catch { /* closing */ }
    try {
      await this.writer?.close();
    } catch { /* closing */ }
    try {
      this.writer?.releaseLock();
    } catch { /* closing */ }
    try {
      await this.readerTask;
    } catch { /* closing */ }
    try {
      await this.port?.close();
    } catch { /* closing */ }
    this.reader = this.writer = null;
    this.readerTask = null;
    this.closing = false;
    this.emit("app", "monitor serial closed");
  }

  async write(text: string) {
    if (!this.writer) throw new Error("monitor serial not open");
    await this.writer.write(enc.encode(text));
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
