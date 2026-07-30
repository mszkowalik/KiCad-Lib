/** What each procedure op accepts — the schema the graphical editor renders.
 *
 *  Field kinds:
 *    text      free string
 *    value     literal OR {parameter} — see ValuePicker
 *    varname   a variable an EARLIER step captured (or a runtime var)
 *    number    numeric input
 *    bool      checkbox
 *    path      dotted response path ("StatusSTS.Wifi.SSId")
 *    commands  a list of "Cmd value" lines (Backlog)
 *    capture   map of variable name -> response path
 *    images    which pinned firmware images this flash step writes
 *    bundle    which berryware bundle this download step sends
 *    check     the functionality this step proves (a name from the catalog)
 *
 *  The ops and their meaning come from the engine (`services/flasher/engine.py`);
 *  keep this table in step with it, and keep VALIDATION on the server — this
 *  file decides what the form LOOKS like, never what is allowed.
 */

export type FieldKind =
  | "text" | "value" | "varname" | "number" | "bool" | "path"
  | "commands" | "capture" | "images" | "bundle" | "check";

export interface Field {
  key: string;
  label: string;
  kind: FieldKind;
  placeholder?: string;
  hint?: string;
  /** shown in the collapsed row summary */
  summary?: boolean;
}

export interface OpSpec {
  op: string;
  title: string;
  /** grouping in the "add step" menu */
  phase: "flash" | "serial" | "dialog" | "check" | "payload";
  blurb: string;
  fields: Field[];
  /** variables this op contributes regardless of `capture` */
  provides?: string[];
}

const TIMEOUT: Field = { key: "timeout", label: "Timeout (s)", kind: "number", placeholder: "10" };
const LABEL: Field = { key: "label", label: "Label", kind: "text", placeholder: "what this step does", summary: true };
const CAPTURE: Field = {
  key: "capture", label: "Capture into variables", kind: "capture",
  hint: "variable name ← dotted path in the response, e.g. topic ← Status.Topic",
};

/** Any step may claim a functionality. Naming one turns this step's own pass or
 *  fail into a green/red cell on the device — nothing else is needed, because
 *  the step already succeeds or fails for a reason. */
const CHECK: Field = {
  key: "check", label: "Proves", kind: "check", summary: true,
  hint: "the functionality this step proves — it becomes a cell in the device's check grid",
};

const RAW_OPS: OpSpec[] = [
  // ---------------------------------------------------------------- flash
  {
    op: "esp_connect", title: "Connect + read MAC", phase: "flash",
    blurb: "Opens the ROM loader, detects the chip and reads the MAC. Put it first — the MAC is what makes a failed run attributable to a device.",
    fields: [LABEL], provides: ["mac", "serial", "chip"],
  },
  {
    op: "erase", title: "Erase flash", phase: "flash",
    blurb: "esptool erase_flash. Wipes settings and filesystem with it.",
    fields: [LABEL, TIMEOUT],
  },
  {
    op: "flash", title: "Write firmware", phase: "flash",
    blurb: "Writes the pinned images at their offsets, MD5-verified against flash.",
    fields: [
      LABEL,
      { key: "images", label: "Images to write", kind: "images", summary: true,
        hint: "pinned on this version; a step may write all of them or only some kinds" },
      { key: "verify_md5", label: "Verify MD5 after writing", kind: "bool" },
      TIMEOUT,
    ],
  },
  {
    op: "esp_reset", title: "Hard reset", phase: "flash",
    blurb: "Pulses the reset line into the new firmware (IO0 high, EN low then high).",
    fields: [LABEL],
  },
  {
    op: "await_reenumerate", title: "Wait for USB to come back", phase: "flash",
    blurb: "Native-USB parts drop off the bus when they reboot; this waits for the port to be openable again.",
    fields: [LABEL, TIMEOUT],
  },
  // --------------------------------------------------------------- serial
  {
    op: "serial_open", title: "Open the monitor port", phase: "serial",
    blurb: "Everything that talks to the firmware needs this first.",
    fields: [LABEL, { key: "baud", label: "Baud", kind: "number", placeholder: "115200" }],
  },
  { op: "serial_close", title: "Close the monitor port", phase: "serial",
    blurb: "Needed before a reset that re-enumerates the USB device.", fields: [LABEL] },
  { op: "reset", title: "Reset while monitoring", phase: "serial",
    blurb: "Pulses reset on the open port (UART bridge) or runs the USB-JTAG sequence and re-opens.",
    fields: [LABEL] },
  { op: "sleep", title: "Wait a fixed time", phase: "serial",
    blurb: "Only for physical settling (relay actuation). Prefer wait_boot or poll_until.",
    fields: [LABEL, { key: "seconds", label: "Seconds", kind: "number", placeholder: "2", summary: true }] },
  {
    op: "wait_boot", title: "Wait until the firmware answers", phase: "serial",
    blurb: "Polls a command until it replies — a reply is proof the app is running. A boot banner cannot be relied on (native USB loses everything printed before the port opens).",
    fields: [
      LABEL, TIMEOUT,
      { key: "probe.cmd", label: "Probe command", kind: "text", placeholder: "Status" },
      { key: "probe.payload", label: "Probe payload", kind: "text", placeholder: "0" },
      { key: "probe.expect_key", label: "Expect key", kind: "text", placeholder: "Status" },
      { key: "probe_every", label: "Probe every (s)", kind: "number", placeholder: "2" },
    ],
  },
  // --------------------------------------------------------------- dialog
  {
    op: "command", title: "Send a command", phase: "dialog",
    blurb: "Sends one console command and waits for a response carrying the expected key.",
    fields: [
      LABEL,
      { key: "cmd", label: "Command", kind: "text", placeholder: "Status", summary: true },
      { key: "payload", label: "Payload", kind: "value", placeholder: "empty = query", summary: true },
      { key: "expect_key", label: "Expect key in the response", kind: "text", placeholder: "defaults to the command" },
      { key: "optional", label: "Silence is acceptable", kind: "bool",
        hint: "for a command that makes the device restart and stop answering" },
      TIMEOUT, CAPTURE,
    ],
  },
  {
    op: "set_and_check", title: "Set and verify", phase: "dialog",
    blurb: "Sends a setting and confirms the device echoed it back.",
    fields: [
      LABEL,
      { key: "cmd", label: "Setting", kind: "text", placeholder: "SSId1", summary: true },
      { key: "value", label: "Value", kind: "value", summary: true },
      { key: "confirm", label: "Expected echo", kind: "value", placeholder: "defaults to the value",
        hint: 'boolean settings echo ON/OFF rather than 1/0' },
      { key: "response_key", label: "Response key", kind: "text", placeholder: "defaults to the setting" },
      TIMEOUT, CAPTURE,
    ],
  },
  {
    op: "backlog", title: "Send several commands at once", phase: "dialog",
    blurb: "One Backlog, one restart — the way to set two settings that must land together (SSID and password).",
    fields: [
      LABEL,
      { key: "commands", label: "Commands", kind: "commands", summary: true },
      { key: "expect_key", label: "Expect key", kind: "text", placeholder: "e.g. the last setting" },
      TIMEOUT,
    ],
  },
  {
    op: "berry", title: "Run Berry code", phase: "dialog",
    blurb: "Sends Br <code> and reads the result.",
    fields: [LABEL, { key: "code", label: "Berry code", kind: "value", summary: true }, TIMEOUT, CAPTURE],
  },
  {
    op: "download_files", title: "Device downloads the berryware", phase: "payload",
    blurb: "The device fetches each file of the pinned bundle over HTTP and every size is verified.",
    fields: [
      LABEL,
      { key: "bundle", label: "Bundle to send", kind: "bundle", summary: true,
        hint: "pinned on this version — autoexec.be always goes last" },
      { key: "retries", label: "Retries per file", kind: "number", placeholder: "3" },
      TIMEOUT,
    ],
  },
  {
    op: "derive_credentials", title: "Derive the MQTT credentials", phase: "payload",
    blurb: "Username = the device's topic, password derived from it and the fleet salt. Stored per device.",
    fields: [
      LABEL,
      { key: "user_var", label: "Username from variable", kind: "varname", placeholder: "topic" },
      { key: "salt_param", label: "Salt parameter", kind: "text", placeholder: "creds_salt" },
    ],
    provides: ["mqtt_user", "mqtt_password"],
  },
  {
    op: "lte_sim_pin", title: "Provision the SIM PIN", phase: "payload",
    blurb: "Sent ONCE and never retried — a re-sent wrong PIN PUK-locks the SIM. Resolution: bench field, then the param set, then a prompt.",
    fields: [
      LABEL,
      { key: "optional", label: "Skip when no PIN is configured", kind: "bool",
        hint: "for SIMs shipped without a PIN" },
      TIMEOUT,
    ],
  },
  // ---------------------------------------------------------------- checks
  {
    op: "poll_until", title: "Poll until a condition holds", phase: "check",
    blurb: "Repeats a command until the response satisfies the condition — how a WiFi or LTE connection is proven.",
    fields: [
      LABEL,
      { key: "cmd", label: "Command", kind: "text", placeholder: "Status", summary: true },
      { key: "payload", label: "Payload", kind: "value", placeholder: "11" },
      { key: "expect_key", label: "Expect key", kind: "text", placeholder: "StatusSTS" },
      { key: "path", label: "Path to test", kind: "path", placeholder: "StatusSTS.Wifi.SSId", summary: true },
      { key: "equals", label: "Must equal", kind: "value" },
      { key: "matches", label: "Must match (regex)", kind: "text" },
      { key: "min", label: "At least", kind: "number" },
      { key: "max", label: "At most", kind: "number" },
      { key: "every", label: "Poll every (s)", kind: "number", placeholder: "2" },
      TIMEOUT, CAPTURE,
    ],
  },
  {
    op: "expect", title: "Expect a log line", phase: "check",
    blurb: "Waits for a raw serial line matching a pattern.",
    fields: [LABEL, { key: "pattern", label: "Pattern (regex)", kind: "text", summary: true }, TIMEOUT],
  },
  {
    op: "assert_equals", title: "Assert a value", phase: "check",
    blurb: "Fails the run when a captured variable is not what it should be.",
    fields: [
      LABEL,
      { key: "var", label: "Variable", kind: "varname", summary: true },
      { key: "equals", label: "Must equal", kind: "value", summary: true },
    ],
  },
  {
    op: "assert_range", title: "Assert a numeric range", phase: "check",
    blurb: "Fails the run when a captured number falls outside the range.",
    fields: [
      LABEL,
      { key: "var", label: "Variable", kind: "varname", summary: true },
      { key: "min", label: "At least", kind: "number", summary: true },
      { key: "max", label: "At most", kind: "number", summary: true },
    ],
  },
];

export const OPS: OpSpec[] = RAW_OPS.map((o) => ({ ...o, fields: [...o.fields, CHECK] }));

export const OP_BY_NAME: Record<string, OpSpec> = Object.fromEntries(OPS.map((o) => [o.op, o]));

export const PHASES: { key: OpSpec["phase"]; label: string }[] = [
  { key: "flash", label: "Flash" },
  { key: "serial", label: "Serial" },
  { key: "dialog", label: "Device dialog" },
  { key: "payload", label: "Payload + credentials" },
  { key: "check", label: "Checks" },
];

/** Variables the engine always provides. Mirrors bundle.RUNTIME_VARS; this is
 *  a dropdown convenience, the server remains the authority. */
export const RUNTIME_VARS = [
  "mac", "serial", "chip", "base_url", "operator", "mqtt_user", "mqtt_password", "sim_pin",
];

/** Nested keys ("probe.cmd") read/write into the step object. */
export function getField(step: Record<string, unknown>, key: string): unknown {
  if (!key.includes(".")) return step[key];
  const [head, tail] = key.split(".");
  const inner = step[head];
  return inner && typeof inner === "object" ? (inner as Record<string, unknown>)[tail] : undefined;
}

export function setField(
  step: Record<string, unknown>, key: string, value: unknown,
): Record<string, unknown> {
  const next = { ...step };
  const drop = value === "" || value === undefined || value === null;
  if (!key.includes(".")) {
    if (drop) delete next[key];
    else next[key] = value;
    return next;
  }
  const [head, tail] = key.split(".");
  const inner = { ...((next[head] as Record<string, unknown>) ?? {}) };
  if (drop) delete inner[tail];
  else inner[tail] = value;
  if (Object.keys(inner).length) next[head] = inner;
  else delete next[head];
  return next;
}

/** Variables available AT a given step index: runtime + everything captured
 *  earlier + what earlier ops provide. */
export function varsBefore(steps: Record<string, unknown>[], index: number, paramKeys: string[]): string[] {
  const out = new Set([...RUNTIME_VARS, ...paramKeys]);
  steps.slice(0, index).forEach((s) => {
    const cap = s.capture as Record<string, string> | undefined;
    if (cap) Object.keys(cap).forEach((k) => out.add(k));
    (OP_BY_NAME[String(s.op)]?.provides ?? []).forEach((k) => out.add(k));
  });
  return [...out].sort();
}
