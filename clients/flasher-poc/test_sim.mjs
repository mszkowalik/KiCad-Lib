// Runs the browser scenario interpreter in Node against a SIMULATED Tasmota
// device whose replies are the REAL serial lines captured by the existing Python
// tool (real_lines.json, pulled from reports/dongle_F8B3B742DAF8_*.json).
// This verifies everything except the USB layer itself: line framing, the
// two-stage JSON parse, command/response matching, set_and_check confirmation,
// captures, asserts, timeouts and the failure path.
import { existsSync, readFileSync, statSync } from "node:fs";
import { Station } from "./station.js";
import { runScenario } from "./runner.js";
import { SCENARIOS, TRANSPORT_PROFILES, autoProfile } from "./scenario.js";

const REAL = JSON.parse(readFileSync(new URL("./real_lines.json", import.meta.url)));
const enc = new TextEncoder();

// --- a fake SerialPort with just the surface Station.serialOpen() touches ----
class FakeTasmota {
  constructor({ dropFriendlyName = false } = {}) {
    this.dropFriendlyName = dropFriendlyName;
    this.friendly = "Dongle";
    this.signals = [];
    this.opened = false;
    this.rx = []; // queue of pending outbound chunks
    this.pending = null;
    this.readable = new ReadableStream({
      start: (c) => {
        this.controller = c;
      },
    });
    this.writable = new WritableStream({
      write: (chunk) => this.onWrite(new TextDecoder().decode(chunk)),
    });
  }
  getInfo() {
    return { usbVendorId: 0x10c4, usbProductId: 0xea60 }; // CP2102 = uart bridge
  }
  async open() {
    this.opened = true;
    // Boot banner, exactly as a real device dumps it after reset.
    setTimeout(() => this.push(REAL.BOOT_WIF), 30);
    setTimeout(() => this.push(REAL.BOOT_HTP), 60);
  }
  async close() {
    this.opened = false;
  }
  async setSignals(s) {
    this.signals.push(s);
  }
  push(line) {
    this.controller.enqueue(enc.encode(line + "\r\n"));
  }
  onWrite(text) {
    for (const raw of text.split("\n")) {
      const cmd = raw.trim();
      if (!cmd) continue;
      const [name, ...rest] = cmd.split(" ");
      const arg = rest.join(" ");
      const reply = this.replyFor(name, arg);
      // Real devices answer after a delay and interleave unrelated log lines.
      setTimeout(() => this.push(REAL.BOOT_WIF), 5);
      if (reply) setTimeout(() => this.push(reply), 40);
    }
  }
  replyFor(name, arg) {
    const n = name.toLowerCase();
    if (n === "status") {
      if (arg === "" || arg === "0") return REAL.STATUS;
      if (arg === "2") return `00:00:05.001 RSL: STATUS2 = {"StatusFWR":{"Version":"14.2.0(CE)","BuildDateTime":"2025-11-05T10:00:00","Core":"3_1_1","SDK":"5.1.4","CpuFrequency":160,"Hardware":"ESP32-D0WD-V3"}}`;
      if (arg === "10") return REAL.STATUS10;
      if (arg === "11") return REAL.STATUS11;
      return REAL.STATUS;
    }
    if (n === "friendlyname1") {
      if (arg) this.friendly = arg;
      if (this.dropFriendlyName) return null; // simulate a device that never answers
      return `00:00:06.100 RSL: RESULT = {"FriendlyName1":"${this.friendly}"}`;
    }
    if (n === "setoption153") return `00:00:04.248 RSL: RESULT = {"SetOption153":"${arg === "1" ? "ON" : "OFF"}"}`;
    return `00:00:07.000 RSL: RESULT = {"${name}":"Done"}`;
  }
}

// The monitor-only part of the CE scenario (no esptool steps — no chip here).
const SIM_SCENARIO = {
  name: "sim: Tasmota talk-and-verify",
  chip: null,
  transport: "uart_bridge",
  flash: { mode: "dio", freq: "40m", size: "detect" },
  monitor_baud: 115200,
  vars: { friendly_name: "CE_PROOF" },
  steps: [
    { op: "serial_open", label: "Open monitor serial", baud: 115200 },
    { op: "wait_boot", label: "Wait for boot marker", timeout: 5, pattern: "HTP: Web server" },
    {
      op: "command",
      label: "Read firmware status",
      cmd: "Status",
      payload: "2",
      expect_key: "StatusFWR",
      timeout: 5,
      capture: { fw_version: "StatusFWR.Version", hardware: "StatusFWR.Hardware" },
    },
    {
      op: "command",
      label: "Read identity",
      cmd: "Status",
      payload: "0",
      expect_key: "Status",
      timeout: 5,
      capture: { topic: "Status.Topic" },
    },
    { op: "set_and_check", label: "Set FriendlyName1", cmd: "FriendlyName1", value: "{friendly_name}", timeout: 5 },
    {
      op: "command",
      label: "Read back FriendlyName1",
      cmd: "FriendlyName1",
      expect_key: "FriendlyName1",
      timeout: 5,
      capture: { friendly_readback: "FriendlyName1" },
    },
    { op: "assert_equals", label: "Verify it stuck", var: "friendly_readback", equals: "{friendly_name}" },
    {
      op: "command",
      label: "Sensor status",
      cmd: "Status",
      payload: "10",
      expect_key: "StatusSNS",
      timeout: 5,
      capture: { sns_time: "StatusSNS.Time", switch1: "StatusSNS.Switch1" },
    },
    { op: "assert_equals", label: "Switch1 is ON", var: "switch1", equals: "ON" },
  ],
};

let failures = 0;
const check = (name, cond, extra = "") => {
  console.log(`${cond ? "  PASS" : "  FAIL"}  ${name}${extra ? " — " + extra : ""}`);
  if (!cond) failures++;
};

// ---------------------------------------------------------------- parse tests
console.log("\n[1] two-stage line parse (port of serial_device.parse_response)");
check("RSL: RESULT = {...} → object", Station.parseLine(REAL.RESULT)?.SetOption153 === "ON");
check("RSL: STATUS = {...} → nested object", Station.parseLine(REAL.STATUS)?.Status?.Topic === "dongle_F8B3B742DAF8");
check("bare JSON line → object", Station.parseLine('{"a":1}')?.a === 1);
check("non-JSON log line → null/string", Station.parseLine("00:00:00.045 HTP: Web server active") !== undefined);
check("case-insensitive key match", Station.matches({ StatusFWR: {} }, "statusfwr") === true);
check("non-match rejected", Station.matches({ StatusSTS: {} }, "StatusFWR") === false);

// ------------------------------------------------------------ happy-path run
console.log("\n[2] full scenario against the simulated device");
const st = new Station(1, () => {});
st.port = new FakeTasmota();
const ok = await runScenario(st, SIM_SCENARIO);
check("scenario passed", ok === true, st.results.error ?? "");
check("captured fw_version", st.results.fw_version === "14.2.0(CE)", String(st.results.fw_version));
check("captured hardware", st.results.hardware === "ESP32-D0WD-V3", String(st.results.hardware));
check("captured topic", st.results.topic === "dongle_F8B3B742DAF8", String(st.results.topic));
check("set_and_check confirmed new value", st.results.friendly_readback === "CE_PROOF");
check("handshake lines deasserted once", JSON.stringify(st.port.signals) === '[{"dataTerminalReady":false,"requestToSend":false}]', JSON.stringify(st.port.signals));
const txLines = st.log.filter((e) => e.dir === "tx").map((e) => e.text);
const rxLines = st.log.filter((e) => e.dir === "rx");
// 5 scenario commands + the wait_boot probe that proves the firmware answers.
check("every command logged as tx", txLines.length === 6, txLines.join(" | "));
check("wait_boot probes instead of trusting the banner", txLines[0] === "Status 0", txLines[0]);
check("all device output logged as rx", rxLines.length > 10, `${rxLines.length} rx lines`);
check("log entries carry wall-clock + monotonic time", st.log.every((e) => e.iso && typeof e.t === "number"));
check("per-step timings recorded", st.timings.length === SIM_SCENARIO.steps.length);

// ------------------------------------------------------------- failure paths
console.log("\n[3] failure paths");
const st2 = new Station(2, () => {});
st2.port = new FakeTasmota({ dropFriendlyName: true });
const ok2 = await runScenario(st2, SIM_SCENARIO);
check("unanswered command fails the run", ok2 === false);
check("error names the step", /FriendlyName1/i.test(st2.results.error ?? ""), st2.results.error);
check("failed run still has full log", st2.log.length > 10, `${st2.log.length} entries`);

const st3 = new Station(3, () => {});
st3.port = new FakeTasmota();
const wrongAssert = structuredClone(SIM_SCENARIO);
wrongAssert.vars.friendly_name = "CE_PROOF";
wrongAssert.steps.at(-1).equals = "OFF"; // Switch1 is ON → must fail
const ok3 = await runScenario(st3, wrongAssert);
check("wrong assertion fails the run", ok3 === false);
check("assert error is explicit", /assert_equals/.test(st3.results.error ?? ""), st3.results.error);

// ------------------------------------- transport profiles + C6 flash map ----
console.log("\n[4] transport profiles");
const fakeInfo = (v, p) => ({ getInfo: () => ({ usbVendorId: v, usbProductId: p }) });
check("Espressif 303a:1001 → usb_serial_jtag", autoProfile(fakeInfo(0x303a, 0x1001)) === "usb_serial_jtag");
check("CP2102 10c4:ea60 → uart_bridge", autoProfile(fakeInfo(0x10c4, 0xea60)) === "uart_bridge");
check(
  "native-USB profile never drives DTR/RTS in monitor mode",
  TRANSPORT_PROFILES.usb_serial_jtag.monitor_signals === null,
);
check("native-USB profile uses the USB-JTAG reset", TRANSPORT_PROFILES.usb_serial_jtag.before === "usb_reset");
check("native-USB profile expects re-enumeration", TRANSPORT_PROFILES.usb_serial_jtag.reenumerates_on_reset === true);
check("bridge profile raises the flash baud", TRANSPORT_PROFILES.uart_bridge.flash_baud === 460800);
check("native-USB profile keeps 115200 (CDC ignores baud)", TRANSPORT_PROFILES.usb_serial_jtag.flash_baud === 115200);

console.log("\n[5] CE_Dongle_V3 flash map vs the firmware project's partition table");
const CSV =
  "/Users/mateuszkowalik/Projects/CE_Dongle_v3_board/firmware/partitions/esp32c6_partition_8MB_app3904k_fs3392k.csv";
const c6 = SCENARIOS.c6_dongle_v3;
const flashStep = c6.steps.find((s) => s.op === "flash");
const at = (addr) => flashStep.files.find((f) => parseInt(f.address, 16) === addr);
if (existsSync(CSV)) {
  const parts = {};
  for (const line of readFileSync(CSV, "utf8").split("\n")) {
    const c = line.split(",").map((x) => x.trim());
    if (c.length >= 5 && !c[0].startsWith("#")) parts[c[0]] = { offset: parseInt(c[3]), size: parseInt(c[4]) };
  }
  check("factory image goes to 0x0", !!at(0x0), JSON.stringify(flashStep.files));
  check(
    `LittleFS image goes to the spiffs offset (${parts.spiffs?.offset?.toString(16)})`,
    !!at(parts.spiffs.offset),
    JSON.stringify(flashStep.files.map((f) => f.address)),
  );
  check(
    `app-only update goes to app0 (0x${parts.app0.offset.toString(16)})`,
    parseInt(SCENARIOS.c6_dongle_v3_app_only.steps.find((s) => s.op === "flash").files[0].address, 16) ===
      parts.app0.offset,
  );
  const fsBin = new URL("./public/firmware/tasmota32c6-CE_DONGLE_V3-littlefs.bin", import.meta.url);
  if (existsSync(fsBin)) {
    check(
      `LittleFS image size == spiffs partition size (${parts.spiffs.size})`,
      statSync(fsBin).size === parts.spiffs.size,
      String(statSync(fsBin).size),
    );
  } else {
    console.log("  SKIP  LittleFS image not copied into public/firmware yet");
  }
} else {
  console.log("  SKIP  CE_Dongle_v3_board firmware project not found — cannot cross-check the partition table");
}
check("blank-device scenario erases first", c6.steps.findIndex((s) => s.op === "erase") === 1);
check(
  "app-only scenario does NOT erase (keeps /.settings + FS)",
  !SCENARIOS.c6_dongle_v3_app_only.steps.some((s) => s.op === "erase"),
);
check(
  "both C6 scenarios wait for re-enumeration after reset",
  [c6, SCENARIOS.c6_dongle_v3_app_only].every((s) => {
    const r = s.steps.findIndex((x) => x.op === "esp_reset");
    return s.steps[r + 1]?.op === "await_reenumerate";
  }),
);
check("C6 flash params stay 'keep' (image header already correct)", c6.flash.mode === "keep" && c6.flash.size === "keep");

console.log(`\n${failures === 0 ? "ALL CHECKS PASSED" : failures + " CHECK(S) FAILED"}`);
process.exit(failures ? 1 : 0);
