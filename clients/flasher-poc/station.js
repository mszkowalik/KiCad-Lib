// One Station = one USB serial adapter = one device slot.
// Everything here runs in the browser: ESP ROM flashing (esptool-js over Web
// Serial) AND the Tasmota text protocol on the same port afterwards.
import { ESPLoader, Transport } from "esptool-js";
import { md5 } from "js-md5";
import { TRANSPORT_PROFILES, autoProfile } from "./scenario.js";

const enc = new TextEncoder();
const dec = new TextDecoder();

export class Station {
  constructor(id, onChange) {
    this.id = id;
    this.onChange = onChange;
    this.port = null;
    this.status = "empty"; // empty | ready | busy | pass | fail
    this.step = "";
    this.progress = null;
    this.log = []; // {t, dir: app|tx|rx|err, text}
    this.vars = {};
    this.results = {};
    this.timings = [];
    this.lastResponse = null;

    // monitor-mode state
    this.monitorBaud = null;
    this.reader = null;
    this.writer = null;
    this.rxLines = []; // queue of parsed lines awaiting a consumer
    this.rxWaiters = [];
    this.readerTask = null;
    this.rxBuf = "";
  }

  emit(dir, text) {
    this.log.push({ t: performance.now(), iso: new Date().toISOString(), dir, text });
    this.onChange?.();
  }
  setStatus(s, step = this.step) {
    this.status = s;
    this.step = step;
    this.onChange?.();
  }

  get portLabel() {
    if (!this.port) return "—";
    const i = this.port.getInfo();
    if (!i.usbVendorId) return "serial port";
    const ids = `${i.usbVendorId.toString(16).padStart(4, "0")}:${i.usbProductId.toString(16).padStart(4, "0")}`;
    return `USB ${ids} · ${TRANSPORT_PROFILES[autoProfile(this.port)].label}`;
  }

  // Which handshake-line behaviour applies: the scenario may pin a profile,
  // otherwise it is decided from the port's USB ids (native USB vs bridge).
  profile(scenario) {
    const key = scenario?.transport ?? autoProfile(this.port);
    return TRANSPORT_PROFILES[key] ?? TRANSPORT_PROFILES.uart_bridge;
  }

  async requestPort() {
    this.port = await navigator.serial.requestPort();
    this.portIds = this.port.getInfo();
    this.emit("app", `port granted: ${this.portLabel}`);
    this.setStatus("ready", "idle");
  }

  attachPort(port) {
    this.port = port;
    this.portIds = port.getInfo();
    this.emit("app", `port attached (previously granted): ${this.portLabel}`);
    this.setStatus("ready", "idle");
  }

  // ---------------------------------------------------------------- esptool

  async espOpen(scenario) {
    const profile = this.profile(scenario);
    const terminal = {
      clean: () => {},
      writeLine: (d) => this.emit("app", `esptool: ${d}`),
      write: (d) => {
        const s = String(d).replace(/[\r\n]+$/, "");
        if (s.trim()) this.emit("app", `esptool: ${s}`);
      },
    };
    this.transport = new Transport(this.port, false);
    this.transport.setDeviceLostCallback(() => this.emit("err", "esptool: device lost (USB re-enumerated?)"));
    this.loader = new ESPLoader({
      transport: this.transport,
      baudrate: profile.flash_baud,
      terminal,
      debugLogging: false,
    });
    this.emit("app", `transport profile: ${profile.label} (before=${profile.before}, flash baud=${profile.flash_baud})`);
    const chip = await this.loader.main(profile.before);
    const mac = await this.loader.chip.readMac(this.loader);
    this.results.chip = chip;
    this.results.mac = mac;
    this.vars.mac = mac;
    if (scenario.chip && !chip.toLowerCase().replace(/[-\s]/g, "").includes(scenario.chip.toLowerCase()))
      throw new Error(`scenario expects ${scenario.chip} but the device reports "${chip}"`);
    this.emit("app", `chip=${chip} mac=${mac}`);
    return { chip, mac };
  }

  async espErase() {
    await this.loader.eraseFlash();
  }

  async espFlash(step, scenario) {
    // A step may carry several images (CE_Dongle_V3: factory @0x0 + LittleFS
    // @0x4B0000). One writeFlash call keeps them in a single stub session.
    const specs = step.files ?? [{ firmware: step.firmware, address: step.address }];
    const fileArray = [];
    for (const spec of specs) {
      const res = await fetch(`/firmware/${spec.firmware}`);
      if (!res.ok) throw new Error(`firmware fetch failed for ${spec.firmware}: ${res.status}`);
      const data = new Uint8Array(await res.arrayBuffer());
      this.emit("app", `image ${spec.firmware} = ${data.length} bytes @ ${spec.address}`);
      fileArray.push({ data, address: parseInt(spec.address, 16) });
    }
    this.results.images = specs.map((s) => `${s.firmware}@${s.address}`);
    await this.loader.writeFlash({
      fileArray,
      flashMode: scenario.flash.mode,
      flashFreq: scenario.flash.freq,
      flashSize: scenario.flash.size,
      eraseAll: false,
      compress: true,
      reportProgress: (_i, written, total) => {
        this.progress = Math.round((written / total) * 100);
        this.onChange?.();
      },
      calculateMD5Hash: step.verify_md5 ? (image) => md5(image) : undefined,
    });
    this.progress = null;
  }

  // Deliberate hard reset: IO0 high (normal boot, NOT download mode), pulse EN.
  //
  // We do NOT use esptool-js's after("hard_reset") on its own: that only calls
  // setRTS(false), i.e. it *releases* a reset it assumes the connect sequence
  // left asserted. UsbJtagSerialReset (and ClassicReset) both END with RTS
  // false, so setRTS(false) is a no-op transition and the chip never restarts —
  // it stays in the flasher stub and the port goes silent. Pulsing RTS
  // ourselves works on both transports: on a bridge RTS drives EN, and on the
  // C6 the USB-Serial/JTAG peripheral resets the chip exactly on
  // (DTR=0, RTS=1), which is the combination we step through here.
  async hardResetPulse(holdMs = 150) {
    const sig = async (s) => {
      if (this.transport) {
        if ("dataTerminalReady" in s) await this.transport.setDTR(s.dataTerminalReady);
        if ("requestToSend" in s) await this.transport.setRTS(s.requestToSend);
      } else {
        await this.port.setSignals(s);
      }
    };
    try {
      await sig({ dataTerminalReady: false }); // IO0 high → boot the app, not the ROM loader
      await sig({ requestToSend: true }); // EN low → chip held in reset
      await new Promise((r) => setTimeout(r, holdMs));
      await sig({ requestToSend: false }); // EN high → run
      this.emit("app", `hard reset pulse (DTR=0, RTS 1→0, hold ${holdMs}ms)`);
    } catch (e) {
      // Native USB: the device can vanish the instant it resets, before we get
      // to release the line. That is a successful reset, not a failure.
      this.emit("app", `reset pulse ended early: ${e.message} (device already rebooting)`);
    }
  }

  async espReset(scenario) {
    const profile = this.profile(scenario);
    if (profile.explicit_hard_reset === false) await this.loader.after(profile.after);
    else await this.hardResetPulse();
    try {
      await this.transport.disconnect();
    } catch (e) {
      // On native USB the device is already gone at this point — expected.
      this.emit("app", `transport close after reset: ${e.message}`);
    }
    this.transport = null;
    this.loader = null;
  }

  // A native-USB chip drops off the bus when it reboots and comes back as a
  // fresh USB device, so the granted SerialPort handle must be re-acquired.
  // Driven by navigator.serial connect/disconnect events, because getPorts()
  // can still hand back the stale handle of a device that just vanished.
  sameDevice(port) {
    const a = this.portIds ?? this.port?.getInfo?.() ?? {};
    const b = port?.getInfo?.() ?? {};
    return a.usbVendorId === b.usbVendorId && a.usbProductId === b.usbProductId;
  }

  noteDisconnect(port) {
    if (!this.sameDevice(port)) return false;
    this.lost = true;
    this.emit("app", "USB device left the bus");
    return true;
  }

  noteConnect(port) {
    if (!this.sameDevice(port)) return false;
    this.port = port;
    this.lost = false;
    this.emit("app", "USB device back on the bus — fresh SerialPort handle");
    this.reappeared?.();
    return true;
  }

  async awaitReenumerate(timeoutMs) {
    this.portIds = this.portIds ?? this.port.getInfo();
    const deadline = performance.now() + timeoutMs;
    // Give the reset a moment to actually drop the device before deciding.
    const arrived = new Promise((resolve) => {
      this.reappeared = resolve;
      setTimeout(resolve, Math.min(timeoutMs, 1500));
    });
    await arrived;
    this.reappeared = null;
    // Definitive test: the port must be openable. On a UART bridge this passes
    // on the first attempt; on a C6 it passes once the CDC device is back.
    for (;;) {
      const ports = await navigator.serial.getPorts();
      const candidate = ports.find((p) => this.sameDevice(p)) ?? this.port;
      try {
        await candidate.open({ baudRate: 115200 });
        await candidate.close();
        this.port = candidate;
        this.emit("app", "port is openable again");
        return;
      } catch (e) {
        if (performance.now() > deadline) throw new Error(`device did not come back: ${e.message}`);
        await new Promise((r) => setTimeout(r, 300));
      }
    }
  }

  // ------------------------------------------------------- monitor serial

  async serialOpen(baud, scenario) {
    if (this.reader) await this.serialClose();
    const profile = this.profile(scenario);
    // Retry: a chip that just rebooted may need a moment before its CDC
    // endpoint accepts an open (native USB), and macOS can hold the tty briefly.
    for (let attempt = 1; ; attempt++) {
      try {
        await this.port.open({ baudRate: baud, bufferSize: 8192 });
        break;
      } catch (e) {
        if (attempt >= 10) throw new Error(`could not open port at ${baud}: ${e.message}`);
        this.emit("app", `open attempt ${attempt} failed (${e.message}) — retrying`);
        await new Promise((r) => setTimeout(r, 400));
      }
    }
    if (profile.monitor_signals) {
      // ONE setSignals call = one USB SET_CONTROL_LINE_STATE: on a native-USB
      // chip this avoids transiting through a line combination the
      // USB-Serial/JTAG peripheral would read as "assert reset" or "enter boot".
      await this.port.setSignals(profile.monitor_signals);
      this.emit("app", `handshake lines set ${JSON.stringify(profile.monitor_signals)}`);
    } else {
      this.emit("app", "handshake lines left untouched (profile says do not drive DTR/RTS)");
    }
    this.monitorBaud = baud;
    this.writer = this.port.writable.getWriter();
    this.reader = this.port.readable.getReader();
    this.readerTask = this.readLoop();
    this.emit("app", `monitor serial open @ ${baud}`);
  }

  async readLoop() {
    try {
      for (;;) {
        const { value, done } = await this.reader.read();
        if (done) break;
        this.rxBuf += dec.decode(value, { stream: true });
        this.schedulePartialFlush();
        let nl;
        while ((nl = this.rxBuf.search(/\r?\n/)) >= 0) {
          const line = this.rxBuf.slice(0, nl);
          this.rxBuf = this.rxBuf.slice(nl + (this.rxBuf[nl] === "\r" ? 2 : 1));
          if (!line.trim()) continue;
          this.emit("rx", line);
          const waiter = this.rxWaiters.shift();
          if (waiter) waiter(line);
          else this.rxLines.push(line);
        }
      }
    } catch (e) {
      if (!this.closing) this.emit("err", `read loop: ${e.message}`);
    }
  }

  // A device that emits a prompt or a partial line without a newline would
  // otherwise stay invisible in the log — which is exactly the case you need to
  // see when a chip is silent or stuck in a loader.
  schedulePartialFlush() {
    clearTimeout(this.partialTimer);
    this.partialTimer = setTimeout(() => {
      if (this.rxBuf.length) {
        this.emit("rx", `${this.rxBuf}  ⟨no newline yet⟩`);
        this.partialShown = this.rxBuf;
      }
    }, 800);
  }

  async serialClose() {
    clearTimeout(this.partialTimer);
    this.closing = true;
    try {
      await this.reader?.cancel();
    } catch {}
    try {
      this.reader?.releaseLock();
    } catch {}
    try {
      await this.writer?.close();
    } catch {}
    try {
      this.writer?.releaseLock();
    } catch {}
    try {
      await this.readerTask;
    } catch {}
    try {
      await this.port.close();
    } catch {}
    this.reader = this.writer = this.readerTask = null;
    this.closing = false;
    this.emit("app", "monitor serial closed");
  }

  drainRx() {
    this.rxLines = [];
    this.rxWaiters = [];
  }

  nextLine(timeoutMs) {
    if (this.rxLines.length) return Promise.resolve(this.rxLines.shift());
    return new Promise((resolve) => {
      const w = (line) => {
        clearTimeout(timer);
        resolve(line);
      };
      const timer = setTimeout(() => {
        const i = this.rxWaiters.indexOf(w);
        if (i >= 0) this.rxWaiters.splice(i, 1);
        resolve(null);
      }, timeoutMs);
      this.rxWaiters.push(w);
    });
  }

  async write(text) {
    this.emit("tx", text.replace(/\n$/, ""));
    await this.writer.write(enc.encode(text));
  }

  // Same two-stage parse as serial_device.py: whole line as JSON, else the
  // payload after the first '=' (Tasmota's "RSL: RESULT = {...}" log format).
  static parseLine(line) {
    try {
      return JSON.parse(line);
    } catch {}
    const m = line.match(/=(.*)/);
    if (m) {
      const body = m[1].trim();
      try {
        return JSON.parse(body);
      } catch {
        return body;
      }
    }
    return null;
  }

  static matches(parsed, key) {
    const k = key.toLowerCase();
    if (parsed && typeof parsed === "object") return Object.keys(parsed).some((x) => x.toLowerCase().includes(k));
    if (typeof parsed === "string") return parsed.toLowerCase().includes(k);
    return false;
  }

  async waitFor(key, timeoutMs) {
    const deadline = performance.now() + timeoutMs;
    for (;;) {
      const remaining = deadline - performance.now();
      if (remaining <= 0) return null;
      const line = await this.nextLine(remaining);
      if (line === null) return null;
      const parsed = Station.parseLine(line);
      if (parsed && Station.matches(parsed, key)) return parsed;
    }
  }

  // Succeed on either a parsed response carrying `key` or a raw line matching
  // `pattern` (used by wait_boot: a probe reply OR a boot banner, whichever).
  async waitForAny(key, pattern, timeoutMs) {
    const deadline = performance.now() + timeoutMs;
    for (;;) {
      const remaining = deadline - performance.now();
      if (remaining <= 0) return null;
      const line = await this.nextLine(remaining);
      if (line === null) return null;
      if (pattern?.test(line)) return line;
      const parsed = Station.parseLine(line);
      if (parsed && key && Station.matches(parsed, key)) return parsed;
    }
  }

  async sendCommand(cmd, payload, expectKey, timeoutMs) {
    this.drainRx();
    const body = payload === undefined || payload === null || payload === "" ? `${cmd}\n` : `${cmd} ${payload}\n`;
    await this.write(body);
    const resp = await this.waitFor(expectKey ?? cmd, timeoutMs);
    this.lastResponse = resp;
    return resp;
  }
}
