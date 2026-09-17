/** One bench slot: a granted serial port, a live log, and the run lifecycle
 *  against the backend engine. Chromium-only (Web Serial). */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  apiBaseUrl,
  createBenchRun,
  createProgrammingRun,
  errorMessage,
  getDeploymentVersion,
  type DeploymentVersionDetail,
} from "../../api";
import {
  listSerialPorts,
  runMarkJob,
  runPrintJob,
  type AgentPort,
  type AgentPrinter,
} from "../../flasher/benchAgent";
import { RunClient, type RunSpec } from "../../flasher/runClient";
import {
  Station,
  readStationName,
  readStationSocket,
  writeStationName,
  type LogDir,
} from "../../flasher/station";
import SocketPicker from "./SocketPicker";
import { useModal } from "../modal";
import { useStickyState } from "../../useStickyState";

export interface StationSlotProps {
  index: number;
  /** null = bench trial: no batch, and a DRAFT version is allowed */
  productionRunId: number | null;
  deploymentVersionId: number | null;
  overrideReason: string;
  simPin: string;
  /** Which project an erased device belongs to, for the run record. */
  projectId: number | null;
  /** What this slot is for. "mark" drops Erase and Test — a marking bench has
   *  no business wiping a device — and renames Program to Mark. */
  mode?: "flash" | "mark";
  /** Start the procedure by itself when a device arrives, armed once per
   *  device. Marking is a one-button job repeated all day, so the button is
   *  the part worth removing; flashing a tray of dongles turned out to be the
   *  same job, and the bench offers it there too since 2026-09-16 — opt-in,
   *  off by default, because the run erases the device first. */
  autoStart?: boolean;
  /** Marking only: what the bench agent reports, polled by the page. The
   *  station shows each machine above its own button, because "the laser is
   *  not answering" and "the printer has no roll" are fixed in two different
   *  places and neither is fixed here. */
  agentUp?: boolean;
  laser?: {
    responsive: boolean;
    busy: boolean | null;
    /** the laser CONTROLLER on the bench machine's USB bus; null = the agent cannot tell */
    laserUsb?: { present: boolean; name: string; ids: string } | null;
  };
  printers?: AgentPrinter[];
  onRunCreated?: (runId: number) => void;
}

interface LogRow {
  dir: LogDir;
  text: string;
}

type SlotStatus = "empty" | "ready" | "busy" | "pass" | "fail" | "aborted";

/** What the port row reports, which is NOT the same as the run's status: a
 *  device can be sitting there ready while the slot has never been run. */
type PortState = "none" | "empty" | "waiting" | "working" | "gone";

/** Chip erase reports no progress at all, so the bar is an estimate: it walks
 *  to 90% over this long and then waits for the real completion. Measured on a
 *  V2 dongle (run 6329): 2.8 s. The estimate is deliberately longer than that,
 *  because a bar that stalls at 90% reads better than one that finishes early
 *  and then sits at 100% doing nothing. */
/** Stations a bench can have, for reading back which sockets are taken.
 *  Mirrors MAX_STATIONS in FlashBench. */
const MAX_SLOTS = 4;

const ERASE_ESTIMATE_MS = 6000;

/** What a serial may be, for anything that goes ON a part (user decision
 *  2026-09-17). The same bounds the engine enforces in `_identity_value`: the
 *  bench checks them so a bad one is caught before a run is created, and the
 *  engine checks them because the bench is not the only way in.
 *
 *  A V2 dongle's MAC is twelve hex characters and shorter product serials
 *  exist. Something outside this range is a capture that went wrong — a whole
 *  Tasmota topic, an empty split — not a serial anybody meant to engrave. */
const SERIAL_MIN = 8;
const SERIAL_MAX = 12;

/** "" when the value is usable, otherwise why it is not. */
function serialProblem(value: string): string {
  if (!value) return "no serial yet";
  if (value.split(/\s/).length > 1) return `"${value}" has a space in it`;
  if (value.length < SERIAL_MIN || value.length > SERIAL_MAX)
    return `"${value}" is ${value.length} characters — a serial is ${SERIAL_MIN} to ${SERIAL_MAX}`;
  return "";
}

/** The label stock this bench runs. The agent can list every roll the
 *  printer's PPD knows — 61 of them — but a dropdown of 61 is a search, not a
 *  choice. Add a row here when a roll is actually bought, and the `size` is
 *  the PPD's own page-size name, which is what `lp -o PageSize=` takes. */
const ROLLS = [
  { size: "w72h154", label: "25 x 54 mm", note: "11352 return address" },
];

/** What a CUPS state reason means in a sentence. The first one is the only one
 *  this printer raises, and it covers three different causes — measured on
 *  2026-09-17 by pulling the roll out mid-job. */
const PRINTER_ADVICE: Record<string, string> = {
  "com.dymo.slot-status-error":
    "there is no roll in it, the lid is open, or the labels are not DYMO Authentic",
  "media-empty-error": "the roll has run out",
  "media-jam": "a label is jammed",
  "cover-open": "the lid is open",
  "offline-report": "it is switched off or unplugged",
};

/** Advice for the failures an operator can act on, rather than a wall of text
 *  on every error.
 *
 *  A device that resets but never reaches the bootloader is the DTR/IO0 half of
 *  the auto-reset circuit not pulling the pin low — measured on one unit
 *  (2026-09-16) where EN worked and IO0 did not, and esptool from a terminal
 *  failed the same way. Holding BOOT grounds IO0 by hand, which is both the
 *  workaround and the test that proves where the fault is.
 */
function hintFor(message: string): string | null {
  if (/failed to connect|no serial data|wrong boot mode|invalid head of packet/i.test(message))
    return "Hold the device's BOOT button while you start, and release it once it says Connecting. If that works, the board's auto-reset circuit is not pulling IO0 low.";
  if (/failed to open serial port/i.test(message))
    return "Unplug the device and plug it back in, then try again.";
  if (/timed out|timeout|head of packet|no response/i.test(message))
    return "The device answered and then stopped. That is usually a marginal USB cable or socket, which fails once the link speeds up — try another one.";
  return null;
}

export default function BenchStation(props: StationSlotProps) {
  const [station] = useState(() => new Station());
  const [status, setStatus] = useState<SlotStatus>("empty");
  const [stepLabel, setStepLabel] = useState("idle");
  const [portLabel, setPortLabel] = useState("—");
  const [progress, setProgress] = useState<number | null>(null);
  // Two bars: how far through THIS step, and how far through the procedure.
  // The first is the one an operator watches during a 90-second flash write.
  const [stepNo, setStepNo] = useState<{ index: number; total: number } | null>(null);
  const [portState, setPortState] = useState<PortState>("none");
  // One marking station, so it is named for the job rather than numbered.
  const nameKey = props.mode === "mark" ? "mark" : props.index;
  const slotName = props.mode === "mark" ? "Marking station" : `Station ${props.index + 1}`;
  const [name, setName] = useState(() => readStationName(nameKey) || slotName);
  const [renaming, setRenaming] = useState(false);
  const [bootWait, setBootWait] = useState(false);
  /** What the last run actually engraved. The operator's check is against the
   *  PART, so this has to be readable from arm's length — it is the one number
   *  a marking bench exists to get right. */
  const [marked, setMarked] = useState<string | null>(null);
  /** MANUAL means the operator supplies the serial instead of the device.
   *  For a unit that is dead, uncased, or whose label was spoiled — the laser
   *  does not care where the string came from, and the box is the same box. */
  const [manual, setManual] = useState(false);
  const [typed, setTyped] = useState("");
  /** What the last run printed, shown beside what it engraved. */
  const [printed, setPrinted] = useState<string | null>(null);
  /** What the device said when it arrived, before anything was pressed.
   *
   *  The marking bench reads the identity as soon as a device appears, so the
   *  operator checks the serial against the part FIRST and a press does not
   *  wait for the firmware. `value` is what would go on the part — the capture
   *  put through the same `take_after` split the action steps use, so the box
   *  and the laser cannot show different strings. */
  const [preread, setPreread] = useState<{ value: string; raw: string } | null>(null);
  const [prereadError, setPrereadError] = useState<string | null>(null);
  const [prereading, setPrereading] = useState(false);
  /** The two machines are armed separately: a bench may be engraving all day
   *  and printing nothing, or the other way round while the laser is down.
   *  One checkbox for both made the working half wait for the broken one. */
  /** Nodes the agent can see: the list for Assign socket…, and the answer to
   *  "is anything plugged into this station's socket". There is no browser path
   *  any more — all serial work is the agent's (decision 0023). */
  const [agentPorts, setAgentPorts] = useState<AgentPort[] | null>(null);
  const [picking, setPicking] = useState(false);
  /** Open by default: the log is what an operator watches during a run, and a
   *  fold they have to open every time is one they stop opening. Remembered
   *  per station once they close it. */
  const [logOpen, setLogOpen] = useStickyState<boolean>(`flasher.log-open.${nameKey}`, true);
  useEffect(() => {
    let alive = true;
    const look = async () => {
      try {
        const ports = await listSerialPorts();
        if (alive) setAgentPorts(ports);
      } catch {
        if (alive) setAgentPorts(null); // the agent is not running
      }
    };
    void look();
    const t = window.setInterval(() => void look(), 2000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);
  const [autoMark, setAutoMark] = useStickyState<boolean>("mark.auto.laser", false);
  const [autoPrint, setAutoPrint] = useStickyState<boolean>("mark.auto.label", false);
  /** Chain the two machines: one press engraves AND labels.
   *
   *  The bench's normal day is both, and doing it with two Automatic boxes
   *  meant the pass started by itself. Linked, the operator keeps the trigger
   *  and still gets one press per device. */
  const [linked, setLinked] = useStickyState<boolean>("mark.linked", false);
  /** The roll and the queue are the BENCH's answer, not the procedure's: the
   *  printer cannot report what is loaded in it (CUPS carries no media-ready
   *  for this driver, measured 2026-09-17), so the operator states it once and
   *  the station remembers. */
  const [roll, setRoll] = useStickyState<string>("mark.roll", ROLLS[0].size);
  const [printer, setPrinter] = useStickyState<string>("mark.printer", "");
  /** The marking procedure's own template and placeholder, so a typed mark and
   *  a run cannot disagree about which drawing a unit gets. */
  const [markVersion, setMarkVersion] = useState<DeploymentVersionDetail | null>(null);
  const [log, setLog] = useState<LogRow[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  // The `finally` that records the run cannot read state it just set, so the
  // outcome is kept where it can.
  const statusRef = useRef<string>("pass");
  const errorRef = useRef<string>("");
  const [prompt, setPrompt] = useState<{ label: string; secret: boolean; resolve: (v: string) => void } | null>(null);
  // The SIM PIN prompt has no cancel: the flashing run is waiting on the answer, so
  // Escape and a click outside must not dismiss it. It still locks the page behind it.
  const modal = useModal(null, { active: !!prompt });
  const clientRef = useRef<RunClient | null>(null);
  const logBox = useRef<HTMLDivElement>(null);
  /** Follow the tail only while the operator is already AT the tail. Read on
   *  every scroll rather than measured after the append, because by then the
   *  new line has already moved the bottom away from them. */
  const logStick = useRef(true);

  const pushLog = useCallback((dir: LogDir, text: string) => {
    setLog((rows) => {
      const next = [...rows, { dir, text }];
      // keep the DOM bounded; the FULL log is in Postgres
      return next.length > 1500 ? next.slice(-1000) : next;
    });
  }, []);

  // Scroll the LOG BOX, never the page. scrollIntoView() walks every scrollable
  // ancestor, so one log line dragged the whole bench view down and an operator
  // reading anything else on the page lost their place four times a second.
  useEffect(() => {
    const box = logBox.current;
    if (box && logStick.current) box.scrollTop = box.scrollHeight;
  }, [log]);

  // Adopt a port the browser has ALREADY granted, so a configured bench needs
  // no click at all: plug the device in and the slot is ready. Without a serial
  // policy this finds nothing and the operator picks once per device, which is
  // the most Web Serial allows for an adapter with no USB serial number.
  /** ONE place that reads the port's state into the UI.
   *
   *  Every path that can change it calls this — adoption, the connect and
   *  disconnect events, picking a port by hand, and the end of a run. It is one
   *  function because it was four, and the two that updated only the label left
   *  the pill saying "device disconnected" until the page was reloaded.
   */
  useEffect(() => {
    if (props.mode !== "mark" || !props.deploymentVersionId) {
      setMarkVersion(null);
      return;
    }
    const ac = new AbortController();
    getDeploymentVersion(props.deploymentVersionId, ac.signal)
      .then(setMarkVersion)
      .catch(() => setMarkVersion(null));
    return () => ac.abort();
  }, [props.mode, props.deploymentVersionId]);

  const syncPort = useCallback(
    (working = false) => {
      setPortLabel(station.portLabel);
      // The agent's list IS the truth: a node that exists is a cable that is
      // plugged in. Nothing in this tab holds a handle, so there is no "gone".
      const node = station.socket;
      const present = !!node && (agentPorts ?? []).some((p) => p.device === node);
      setPortState(working ? "working" : !node ? "none" : present ? "waiting" : "empty");
      setStatus((cur) => (cur === "empty" && present ? "ready" : cur));
    },
    [station, agentPorts],
  );

  // A cable arriving or leaving is a change in the agent's list.
  useEffect(() => {
    syncPort();
  }, [agentPorts, syncPort]);

  // The station talks BEFORE a run too. RunClient wires this up when a run
  // starts, which left port adoption, re-acquisition and every open failure
  // reporting into a no-op — the operator saw an idle slot and no reason why.
  useEffect(() => {
    station.onEvent = pushLog;
    // Not a modal: the bench keeps retrying while the operator reaches for the
    // device, so this is a notice with a way out, not a question that blocks.
    station.onBootWait = setBootWait;
    // The slot number is the tie-break when an unclaimed port appears, so it
    // has to be registered before anything can arrive.
    station.register(props.index);
    return () => station.unregister();
    // NOT `syncPort` or `adopt`: both depend on the agent's port list, which is
    // re-polled every two seconds, so this effect tore the station down and
    // built it up again on every poll — visible as "port released" scrolling
    // through a running flash (bench, 2026-09-17).
  }, [station, pushLog, props.index]);

  // No navigator.serial listeners: this tab holds no port, so a plug event
  // means nothing here. The agent's port list, polled above, is the signal.

  /** Sockets other stations own, so the picker can say so. */
  const takenBy = useMemo(() => {
    const out: Record<string, string> = {};
    for (let i = 0; i < MAX_SLOTS; i++) {
      if (i === props.index && props.mode !== "mark") continue;
      const node = readStationSocket(i);
      if (node) out[node] = readStationName(i) || `Station ${i + 1}`;
    }
    // The marking station is keyed "mark", not by slot.
    if (props.mode !== "mark") {
      const markNode = readStationSocket("mark" as unknown as number);
      if (markNode) out[markNode] = readStationName("mark") || "Marking station";
    }
    return out;
  }, [props.index, props.mode, picking]);

  /** Assign this station a USB socket.
   *
   *  A LIVE list, not Chrome's port picker: the agent sees the real `/dev/cu.*`
   *  names, and `SocketPicker` watches them while it is open so the operator can
   *  plug the device in and take the row that appears (decision 0023, user
   *  request 2026-09-17). Nothing here asks the browser for a serial
   *  permission, which is what makes the bench browser-independent.
   */
  const pickPort = () => {
    setError(null);
    setPicking(true);
  };

  /** Chip erase, straight from the browser and deliberately NOT a run.
   *
   *  It is a workshop action — clear a unit before re-programming it — and a
   *  row per erase would bury the production runs it sits next to. The
   *  programming run that follows is the traceable event (user decision
   *  2026-09-16). esptool reports no progress for an erase, so the bar is
   *  estimated; see ERASE_ESTIMATE_MS.
   */
  const erase = async () => {
    try {
      await station.ensurePort();
    } catch (err) {
      setError(errorMessage(err));
      return;
    }
    setError(null);
    setHint(null);
    setStatus("busy");
    syncPort(true);
    setStepNo({ index: 0, total: 1 });
    setStepLabel("erasing flash");
    const startedAt = new Date().toISOString();
    // Everything the station says during the erase, so a failure is readable
    // afterwards instead of only while it is on screen.
    const lines: { dir: string; text: string }[] = [];
    const record = station.onEvent;
    station.onEvent = (dir, text) => {
      lines.push({ dir, text });
      record(dir, text);
    };
    let mac = "";
    let chip = "";
    const started = performance.now();
    const ticker = setInterval(() => {
      const share = Math.min(1, (performance.now() - started) / ERASE_ESTIMATE_MS);
      setProgress(Math.round(share * 90));
    }, 100);
    try {
      // 115200: no baud change, so a marginal board cannot fall over on the
      // one step an erase does not need. See Station.espOpen.
      ({ mac, chip } = await station.espOpen("", 115200));
      await station.espErase();
      setProgress(100);
      statusRef.current = "pass";
      errorRef.current = "";
      setStatus("pass");
      setStepLabel("flash erased");
    } catch (err) {
      const message = errorMessage(err);
      statusRef.current = "fail";
      errorRef.current = message;
      setError(message);
      setHint(hintFor(message));
      setStatus("fail");
      setStepLabel("erase failed");
    } finally {
      clearInterval(ticker);
      station.onEvent = record;
      await station.cleanup();
      setStepNo(null);
      setProgress(null);
      syncPort();
      // Once the MAC is known the attempt belongs in the device's history —
      // a failure that leaves no trace is the one you meet again next batch.
      // An erase that never reached a MAC has no device to attach to.
      if (mac && props.projectId) {
        try {
          const made = await createBenchRun({
            action: "erase", project_id: props.projectId, mac, chip,
            status: statusRef.current, error: errorRef.current,
            station: `slot ${props.index + 1}`,
            started_at: startedAt, log: lines,
          });
          setRunId(made.run_id);
        } catch (err) {
          pushLog("err", `could not record this erase: ${errorMessage(err)}`);
        }
      }
    }
  };

  /** Engrave what the operator typed, with no device in the loop.
   *
   *  It goes through `runMarkJob` — the SAME path a marking run takes — so the
   *  template, the placeholder and the agent are identical and only the source
   *  of the string differs.
   *
   *  It is NOT recorded (user decision 2026-09-17). A typed value names no run
   *  and proves nothing about a device — the operator is replacing a spoiled
   *  label or engraving a bare part — and a history row that says a unit was
   *  marked, with nobody able to say against what, is worse than no row.
   *  Everything the two BUTTONS do runs the procedure, and that still records.
   */
  const markTyped = async () => {
    const step = (markVersion?.steps ?? []).find(
      (x) => (x as { op?: string }).op === "mark_laser",
    ) as
      | { template?: string; placeholder?: string; job_timeout?: number; device?: string }
      | undefined;
    const files = markVersion?.files ?? [];
    const file = step?.template
      ? files.find((f) => f.filename === step.template)
      : files.length === 1
        ? files[0]
        : undefined;
    const value = typed.trim().toUpperCase();
    if (!file || serialProblem(value)) return;

    setError(null);
    setHint(null);
    setStatus("busy");
    setStepLabel(`engraving ${value}`);
    setMarked(null);
    let out: { status: string; error?: string };
    try {
      out = await runMarkJob(
        apiBaseUrl(),
        {
          fileVersionId: file.device_file_version_id,
          filename: file.filename,
          value,
          placeholder: step?.placeholder,
          device: step?.device,
          start: true,
          jobTimeoutS: Number(step?.job_timeout ?? 300),
        },
        (dir, text) => pushLog((dir as LogDir) ?? "app", text),
      );
    } catch (err) {
      out = { status: "fail", error: errorMessage(err) };
      pushLog("err", out.error ?? "");
    }
    if (out.status === "pass") {
      setMarked(value);
      setStatus("pass");
      setStepLabel("engraved");
      // The chain means one press does both, typed or read. Only after the
      // engraving passed: a label for a part the laser never marked is worse
      // than no label.
      if (chained) await printTyped();
    } else {
      setError(out.error ?? "the mark failed");
      setStatus("fail");
      setStepLabel("mark failed");
    }
  };

  /** Print what the operator typed, with no device in the loop.
   *
   *  The twin of the manual mark, through `runPrintJob` — the same path a run
   *  takes — and unrecorded for the same reason. A spoiled label is the
   *  commonest thing on a marking bench, and reprinting one is not a new fact
   *  about the unit.
   */
  const printTyped = async () => {
    const value = typed.trim().toUpperCase();
    if (serialProblem(value)) return;
    setError(null);
    setHint(null);
    setStatus("busy");
    setStepLabel(`printing ${value}`);
    setPrinted(null);
    let out: { status: string; error?: string };
    try {
      out = await runPrintJob(
        { value, printer: printer || undefined, roll, ...labelStepArgs() },
        (dir, text) => pushLog((dir as LogDir) ?? "app", text),
      );
    } catch (err) {
      out = { status: "fail", error: errorMessage(err) };
      pushLog("err", out.error ?? "");
    }
    if (out.status === "pass") {
      setPrinted(value);
      setStatus("pass");
      setStepLabel("printed");
    } else {
      setError(out.error ?? "the label did not print");
      setStatus("fail");
      setStepLabel("print failed");
    }
  };

  /** The step that reads the device's identity, and the split applied to it.
   *
   *  Read off the VERSION rather than hard-coded, so the bench asks the device
   *  exactly what the procedure asks it. A marking version that captured
   *  something else would pre-read that instead, with no change here.
   */
  const identityPlan = useCallback(() => {
    const steps = (markVersion?.steps ?? []) as Record<string, unknown>[];
    const read = steps.find(
      (x) => x.op === "command" && Object.keys((x.capture as object) ?? {}).length,
    );
    if (!read) return null;
    const capture = read.capture as Record<string, string>;
    const path = Object.values(capture)[0];
    const action = steps.find((x) => x.op === "mark_laser" || x.op === "print_label");
    return {
      cmd: [read.cmd, read.payload].filter(Boolean).join(" "),
      expectKey: String(read.expect_key ?? read.cmd ?? "Status"),
      path,
      takeAfter: action?.take_after ? String(action.take_after) : "",
    };
  }, [markVersion]);

  /** Ask the device who it is, the moment it arrives.
   *
   *  Measured on runs 6372-6374: `wait_boot` costs 0.7-1.1 s of every press and
   *  its only job is to wait for the firmware to answer. Doing it once when the
   *  device is plugged in gets the serial on screen before the operator presses
   *  anything, and lets the run leave that step out. The run still reads the
   *  identity itself, so nothing here is taken on trust.
   */
  const preRead = useCallback(async () => {
    const plan = identityPlan();
    if (!plan) return;
    setPrereading(true);
    setPrereadError(null);
    try {
      const reply = await station.probeIdentity(
        markVersion?.monitor_baud ?? 115200,
        plan.cmd,
        plan.expectKey,
      );
      const raw = String(
        plan.path.split(".").reduce<unknown>(
          (o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined),
          reply,
        ) ?? "",
      );
      if (!raw) throw new Error(`the device answered, but said nothing at ${plan.path}`);
      const value = (plan.takeAfter ? raw.split(plan.takeAfter).pop() ?? raw : raw).toUpperCase();
      const bad = serialProblem(value);
      // A device that answers with something that is not a serial is not an
      // identified device. Saying so here stops a run that would fail on its
      // action step anyway, after the part is already in the fixture.
      if (bad) throw new Error(`${bad}. The device said ${raw}`);
      setPreread({ value, raw });
      pushLog("app", `device identified as ${raw} before any action`);
    } catch (err) {
      setPreread(null);
      setPrereadError(errorMessage(err));
      pushLog("err", `could not read the device: ${errorMessage(err)}`);
    } finally {
      setPrereading(false);
    }
  }, [identityPlan, markVersion, station, pushLog]);

  /** What the version says about its label, for a print that runs no steps.
   *  The same reason the manual mark reads the template off the step: a typed
   *  label and a run's label must not disagree about what they are. */
  const labelStepArgs = () => {
    const step = (markVersion?.steps ?? []).find(
      (x) => (x as { op?: string }).op === "print_label",
    ) as { dots?: number; rotate?: boolean; copies?: number; job_timeout?: number } | undefined;
    return {
      dots: Number(step?.dots ?? 3),
      rotate: step?.rotate !== false,
      copies: Number(step?.copies ?? 1),
      jobTimeoutS: Number(step?.job_timeout ?? 120),
    };
  };

  /** Run the procedure. `skipOps` is how the two marking buttons differ.
   *
   *  ONE procedure reads the device once and then acts on it. Which action
   *  this press asked for is the bench's business, so it travels in the hello
   *  rather than in the version — and the engine only honours it for the two
   *  action ops, so a bench can never quietly change what a unit was made
   *  under (decision 0021).
   */
  const run = async (
    versionId: number | null = props.deploymentVersionId,
    skipOps: string[] = [],
  ) => {
    if (!props.productionRunId && !versionId) {
      setError("Pick a batch, or a deployment version for a bench trial.");
      return;
    }
    // Check the socket before creating a run: a station with none cannot
    // program anything, and a run row that exists for that is noise.
    try {
      await station.ensurePort();
    } catch (err) {
      setError(errorMessage(err));
      return;
    }
    setError(null);
    setHint(null);
    setLog([]);
    setStatus("busy");
    syncPort(true);
    setStepLabel("creating run…");
    let created: { run_id: number; draft_run: boolean };
    try {
      created = await createProgrammingRun({
        production_run_id: props.productionRunId,
        deployment_version_id: versionId,
        station: `slot ${props.index + 1}`,
        override_reason: props.overrideReason,
      });
    } catch (err) {
      setError(errorMessage(err));
      setStatus("ready");
      return;
    }
    setRunId(created.run_id);
    props.onRunCreated?.(created.run_id);
    if (created.draft_run) pushLog("app", "=== BENCH TRIAL of a DRAFT version ===");

    setMarked(null);
    setPrinted(null);
    const params: Record<string, string> = {};
    if (props.simPin.trim()) params.sim_pin = props.simPin.trim();
    // `operator` is NOT a bench param: the server stamps the run with the
    // signed-in account and the engine seeds `{operator}` from that row.

    const client = new RunClient(station, created.run_id, params, {
      onSpec: (spec: RunSpec) => {
        pushLog(
          "app",
          `=== ${spec.deployment_name} v${spec.deployment_version_no}` +
            `${spec.draft ? " (draft)" : ""} — ${spec.steps.length} steps ===`,
        );
      },
      onState: (s) => {
        setStepLabel(s.label);
        setStepNo({ index: s.index, total: s.total });
      },
      onLog: pushLog,
      onProgress: setProgress,
      onMarked: setMarked,
      onPrinted: setPrinted,
      onPrompt: (_field, label, secret) =>
        new Promise<string>((resolve) => setPrompt({ label, secret, resolve })),
      onDone: (st, err, results) => {
        if (err) setHint(hintFor(err));
        if (typeof results.marked === "string") setMarked(results.marked);
        if (typeof results.printed === "string") setPrinted(results.printed);
        setStatus(st === "pass" ? "pass" : st === "aborted" ? "aborted" : "fail");
        setStepLabel(st === "pass" ? "finished" : st);
        setStepNo(null);
        setProgress(null);
        syncPort();
        if (err) setError(err);
      },
    },
    { printer: printer || undefined, roll, skipOps },
    );
    clientRef.current = client;
    try {
      await client.start();
    } catch (err) {
      setError(errorMessage(err));
      setStatus("fail");
    } finally {
      clientRef.current = null;
    }
  };

  const abort = () => clientRef.current?.abort();

  const answerPrompt = (value: string) => {
    prompt?.resolve(value);
    setPrompt(null);
  };

  const busy = status === "busy";
  const devicePresent = portState === "waiting" || portState === "working";
  const canRun = devicePresent && !busy && (props.productionRunId || props.deploymentVersionId);
  /** The device answered a moment ago, so the run has nothing to wait for. The
   *  identity is still read inside the run, by the step after this one. */
  const skipRead = preread ? ["wait_boot"] : [];
  const marking = props.mode === "mark";

  // --- what each machine is doing, as its own answer ------------------------
  // Two hops for the laser and two for the printer, and the agent is the hop
  // they share. A pill that said "not ready" for all four would be true and
  // useless: each of these is fixed somewhere different.
  const printers = props.printers ?? [];
  const chosenPrinter =
    printers.find((x) => x.queue === printer) ??
    printers.find((x) => x.default) ??
    printers[0] ??
    null;
  // LightBurn answering is not the laser being there: STATUS says OK with the
  // board unplugged, so the agent also reports whether the controller is on USB.
  const laserMissing = props.laser?.laserUsb?.present === false;
  const laserReady = Boolean(props.agentUp && props.laser?.responsive && !laserMissing);
  const printerReady = Boolean(props.agentUp && chosenPrinter?.ok);
  const hasLabelStep = (markVersion?.steps ?? []).some(
    (x) => (x as { op?: string }).op === "print_label",
  );

  const laserPill = !props.agentUp
    ? { text: "agent down", tone: "err", note: "The bench agent is not running on this machine." }
    : !props.laser?.responsive
      ? {
          text: "not answering",
          tone: "warn",
          note:
            "LightBurn is not started, a dialog is waiting for a click, or the licence is " +
            "Core — Core cannot drive a galvo, and fails silently.",
        }
      : laserMissing
        ? {
            text: "no laser on USB",
            tone: "err",
            note: "LightBurn answers, but the laser controller is not on this machine's USB bus. " +
              "Is the marker powered on and plugged in?",
          }
        : props.laser.busy
          ? { text: "busy", tone: "neutral", note: "A job is running." }
          : {
              text: "ready",
              tone: "ok",
              note: props.laser.laserUsb
                ? `LightBurn is answering and the ${props.laser.laserUsb.name} is on USB.`
                : "LightBurn is answering.",
            };

  const printerPill = !props.agentUp
    ? { text: "agent down", tone: "err", note: "The bench agent is not running on this machine." }
    : !chosenPrinter
      ? { text: "none", tone: "warn", note: "No printer on this machine. Add one in System Settings." }
      : chosenPrinter.ok
        ? { text: "ready", tone: "ok", note: `${chosenPrinter.queue} is ready.` }
        : {
            text: "check it",
            tone: "err",
            note: `${chosenPrinter.queue}: ${chosenPrinter.reasons}${
              PRINTER_ADVICE[chosenPrinter.reasons] ? ` — ${PRINTER_ADVICE[chosenPrinter.reasons]}` : ""
            }`,
          };

  // Start by itself when a device arrives, ONCE per device. The arm is dropped
  // when the port goes live and only restored when it goes away again, so a
  // finished part sitting in the fixture is not marked twice — the operator
  // has to take it out, which they were going to do anyway.
  // Once per device. Re-armed only when the port goes away, so a finished part
  // sitting in the fixture is not re-read every render.
  const readArmed = useRef(true);
  useEffect(() => {
    if (!marking) return;
    if (portState !== "waiting") {
      if (portState === "none" || portState === "gone" || portState === "empty") {
        readArmed.current = true;
        setPreread(null);
        setPrereadError(null);
      }
      return;
    }
    if (!readArmed.current || busy || !markVersion) return;
    readArmed.current = false;
    void preRead();
  }, [marking, portState, busy, markVersion, preRead]);

  const autoArmed = useRef(true);
  // Which actions an automatic pass should perform. A bench may be engraving
  // all day and printing nothing, or printing while the laser is down, so the
  // two are armed separately and a machine that is not ready arms nothing.
  // Nothing starts until the device has said who it is (user decision
  // 2026-09-17): a press that cannot name the part is not worth the label.
  const identified = !marking || Boolean(preread);
  /** The chain, as it actually applies: a version with no label step has
   *  nothing to chain to, whatever the switch says. */
  const chained = marking && linked && hasLabelStep;
  /** Manual mode's own verification. The read path is checked in `preRead`. */
  const typedProblem = manual ? serialProblem(typed.trim().toUpperCase()) : "";
  const autoMarkNow = marking ? autoMark && laserReady && identified : false;
  const autoPrintNow = marking
    ? (autoPrint || (linked && autoMarkNow)) && printerReady && hasLabelStep && identified
    : false;
  const autoSkip = [
    ...(autoMarkNow ? [] : ["mark_laser"]),
    ...(autoPrintNow ? [] : ["print_label"]),
    ...skipRead,
  ];
  const autoOn = marking ? autoMarkNow || autoPrintNow : Boolean(props.autoStart);
  useEffect(() => {
    if (!autoOn) return;
    if (portState !== "waiting") {
      if (portState === "none" || portState === "gone") autoArmed.current = true;
      return;
    }
    if (!autoArmed.current || busy || !canRun) return;
    autoArmed.current = false;
    void run(props.deploymentVersionId, marking ? autoSkip : []);
    // `run` is stable for the life of the slot; listing it would re-fire this
    // on every render that redefines it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOn, autoMarkNow, autoPrintNow, portState, busy, canRun]);
  const overall = stepNo ? Math.round((stepNo.index / stepNo.total) * 100) : null;

  return (
    <div className={`card pad bench-station${marking ? " is-mark" : ""}`}>
      <div className="toolbar">
        {renaming ? (
          <input
            className="bench-name"
            value={name}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onBlur={() => {
              // An empty name is not a name: fall back to the slot, and store
              // nothing so the default follows the slot if stations are moved.
              const kept = name.trim() || slotName;
              setName(kept);
              writeStationName(nameKey, kept === slotName ? "" : kept);
              setRenaming(false);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              if (e.key === "Escape") {
                setName(readStationName(nameKey) || slotName);
                setRenaming(false);
              }
            }}
          />
        ) : (
          <>
            <strong className="bench-name-text">{name}</strong>
            <button
              type="button"
              className="cat-act"
              title={`Rename ${name}`}
              onClick={() => setRenaming(true)}
            >
              ✎
            </button>
          </>
        )}
        {runId ? (
          <Link className="val-link" to={`/production/flash-runs/${runId}`}>
            run #{runId}
          </Link>
        ) : null}
      </div>
      {marking ? null : <div className="muted bench-slot">{slotName}</div>}

      {marking ? (
        /* Two columns, because the bench does two jobs on one device and each
           has its own machine. Left is the DEVICE: what its serial is, whether
           its port is live, and what the station is doing. Right is the two
           things that can be done to it, each under the status of the machine
           that does it — a laser that is not answering and a printer with no
           roll are fixed in different rooms, and one shared status pill sent
           the operator to the wrong one. */
        <div className="bench-mark-cols">
          <div className="bench-mark-left">
            {marking ? (
                    <div className="bench-serial">
                      <div className="bench-serial-row">
                        <span className="muted">Serial</span>
                        <label className="field-check bench-manual-toggle" title="Type the serial yourself, for a unit that cannot be read">
                          <input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} />
                          <span>Manual</span>
                        </label>
                      </div>
                      <input
                        className="text mono bench-serial-box"
                        value={manual ? typed : (marked ?? preread?.value ?? "")}
                        readOnly={!manual}
                        placeholder={
                          manual
                            ? "D4E9F4F4DFD4"
                            : prereading
                              ? "asking the device…"
                              : "read from the device"
                        }
                        onChange={(e) => setTyped(e.target.value.toUpperCase())}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && manual && !busy && !typedProblem)
                            void markTyped();
                        }}
                      />
                      {/* Why the buttons are dead. Without this the station
                          looks broken rather than waiting for a device that
                          has not said who it is. */}
                      {manual && typedProblem && typed.trim() ? (
                        <div className="bench-did">{typedProblem}</div>
                      ) : null}
                      {!manual && !preread ? (
                        <div className="bench-did">
                          {prereading
                            ? "Reading the device…"
                            : prereadError
                              ? `${prereadError} — unplug it and plug it back in, or tick Manual.`
                              : "Waiting for a device."}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
            <div className={`bench-verdict v-${status}`}>{VERDICT[status]}</div>
            <div className="bench-progress">
                    <div className="bench-step">
                      {stepNo ? <span className="mono dim">{stepNo.index + 1}/{stepNo.total}</span> : null}{" "}
                      {stepLabel}
                    </div>
                    <Bar label="step" pct={progress} />
                    <Bar label="all" pct={overall} />
                  </div>
            {busy ? (
              <div className="btn-row">
                <button type="button" className="btn btn-danger btn-sm" onClick={abort}>
                  Abort
                </button>
              </div>
            ) : null}
            <div className="bench-port-row">
                    <span className={`pill ${PORT_PILL[portState]}`}>{PORT_TEXT[portState]}</span>
                    {portLabel && portLabel !== "—" ? (
                      <span className="mono dim bench-port" title={portLabel}>
                        {portLabel}
                      </span>
                    ) : null}
                    {station.assigned ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => {
                          station.unbind();
                          syncPort();
                        }}
                        disabled={busy}
                        title="Give up this socket. The station stops taking whatever is plugged into it, and another station can claim it."
                      >
                        Free socket
                      </button>
                    ) : (
                      <button type="button" className="btn btn-sm" onClick={pickPort} disabled={busy}>
                        Assign socket…
                      </button>
                    )}
                  </div>
          </div>

          <div className="bench-mark-right">
            <div className="bench-action">
              <div className="bench-action-head">
                <strong>Laser</strong>
                <span className={`pill ${laserPill.tone}`} title={laserPill.note}>
                  {laserPill.text}
                </span>
              </div>
              <button
                type="button"
                className="btn btn-primary bench-action-btn"
                onClick={() =>
                  void (manual
                    ? markTyped()
                    : run(
                        props.deploymentVersionId,
                        chained ? [...skipRead] : ["print_label", ...skipRead],
                      ))
                }
                disabled={
                  manual
                    ? busy || !!typedProblem || !markVersion || (chained && !printerReady)
                    : !canRun || !identified || (chained && !printerReady)
                }
                title={
                  chained && !printerReady
                    ? "Linked to the printer, and the printer is not ready — fix it, or drop the link"
                    : chained
                      ? "Engrave, then print the label"
                      : "Engrave only"
                }
              >
                {chained ? "Mark + label" : "Mark"}
              </button>
              <label className="field-check" title="Engrave by itself when a device is plugged in">
                <input
                  type="checkbox"
                  checked={autoMark}
                  onChange={(e) => setAutoMark(e.target.checked)}
                />
                <span>Automatic</span>
              </label>
              {marked ? <div className="bench-did mono">engraved {marked}</div> : null}
            </div>

            {/* The link lives between the two boxes because that is what it
                joins. Off, the bench does one thing per press; on, the laser
                button carries the label with it. */}
            {hasLabelStep ? (
              <button
                type="button"
                className={`bench-chain${chained ? " is-on" : ""}`}
                aria-pressed={chained}
                onClick={() => setLinked(!linked)}
                disabled={busy}
                title={
                  chained
                    ? "Linked: one press engraves and then prints. Click to separate them."
                    : "Separate: each button does its own job. Click to link them."
                }
              >
                <span className="bench-chain-icon" aria-hidden="true">
                  {chained ? "🔗" : "⛓"}
                </span>
                <span>{chained ? "linked" : "link"}</span>
              </button>
            ) : null}

            <div className="bench-action">
              <div className="bench-action-head">
                <strong>Printer</strong>
                <span className={`pill ${printerPill.tone}`} title={printerPill.note}>
                  {printerPill.text}
                </span>
              </div>
              <button
                type="button"
                className="btn btn-primary bench-action-btn"
                onClick={() =>
                  void (manual
                    ? printTyped()
                    : run(props.deploymentVersionId, ["mark_laser", ...skipRead]))
                }
                disabled={
                  manual ? busy || !!typedProblem : !canRun || !hasLabelStep || !identified
                }
                title={
                  hasLabelStep || manual
                    ? "Print the barcode label for this device"
                    : "This marking procedure has no label step"
                }
              >
                Print label
              </button>
              {/* Only when there is a choice to make. One printer is the normal
                  bench, and a select with one entry is furniture. */}
              {printers.length > 1 ? (
                <select
                  className="bench-roll"
                  value={chosenPrinter?.queue ?? ""}
                  onChange={(e) => setPrinter(e.target.value)}
                  disabled={busy}
                  title="Which printer on this machine"
                >
                  {printers.map((x) => (
                    <option key={x.queue} value={x.queue}>
                      {x.queue}
                    </option>
                  ))}
                </select>
              ) : null}
              <select
                className="bench-roll"
                value={roll}
                onChange={(e) => setRoll(e.target.value)}
                disabled={busy}
                title="Which label roll is in the printer. It cannot be read from the printer, so it is stated here."
              >
                {ROLLS.map((r) => (
                  <option key={r.size} value={r.size}>
                    {r.label}
                  </option>
                ))}
              </select>
              <label className="field-check" title="Print by itself when a device is plugged in">
                <input
                  type="checkbox"
                  checked={autoPrint}
                  onChange={(e) => setAutoPrint(e.target.checked)}
                />
                <span>Automatic</span>
              </label>
              {printed ? <div className="bench-did mono">printed {printed}</div> : null}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="btn-row">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => void (manual ? markTyped() : run())}
                    disabled={manual ? busy || !typed.trim() || !markVersion : !canRun}
                  >
                    {marking ? "Mark" : "Program"}
                  </button>
                  {marking ? null : (
                    <button type="button" className="btn btn-sm" onClick={() => void erase()}
                            disabled={!devicePresent || busy}>
                      Erase
                    </button>
                  )}
                  {busy ? (
                    <button type="button" className="btn btn-danger btn-sm" onClick={abort}>
                      Abort
                    </button>
                  ) : null}
                </div>

          <div className={`bench-verdict v-${status}`}>{VERDICT[status]}</div>

          <div className="bench-progress">
                  <div className="bench-step">
                    {stepNo ? <span className="mono dim">{stepNo.index + 1}/{stepNo.total}</span> : null}{" "}
                    {stepLabel}
                  </div>
                  <Bar label="step" pct={progress} />
                  <Bar label="all" pct={overall} />
                </div>
        </>
      )}

      {bootWait ? (
              <div className="banner-warn bench-bootwait">
                <strong>Hold the BOOT button on the device.</strong> This board does not enter
                download mode by itself. Keep holding — the bench retries every second until it
                answers.
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    station.cancelBootWait = true;
                  }}
                >
                  Stop waiting
                </button>
              </div>
            ) : null}
      {error ? (
              <div className="banner-error">
                {error}
                {hint ? <div className="bench-hint">{hint}</div> : null}
              </div>
            ) : null}
      {marking ? null : (
        <div className="bench-port-row">
                <span className={`pill ${PORT_PILL[portState]}`}>{PORT_TEXT[portState]}</span>
                {portLabel && portLabel !== "—" ? (
                  <span className="mono dim bench-port" title={portLabel}>
                    {portLabel}
                  </span>
                ) : null}
                {station.assigned ? (
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => {
                      station.unbind();
                      syncPort();
                    }}
                    disabled={busy}
                    title="Give up this socket. The station stops taking whatever is plugged into it, and another station can claim it."
                  >
                    Free socket
                  </button>
                ) : (
                  <button type="button" className="btn btn-sm" onClick={pickPort} disabled={busy}>
                    Assign socket…
                  </button>
                )}
              </div>
      )}

      <details
        className="bench-log-wrap"
        open={logOpen}
        onToggle={(e) => setLogOpen((e.currentTarget as HTMLDetailsElement).open)}
      >
        <summary className="muted">Log ({log.length})</summary>
        <div
          className="flash-log mono"
          ref={logBox}
          onScroll={() => {
            const box = logBox.current;
            if (box) logStick.current = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
          }}
        >
          {log.map((row, i) => (
            <div key={i} className={`fl-${row.dir}`}>
              {row.dir === "tx" ? "\u2192 " : row.dir === "rx" ? "\u2190 " : ""}
              {row.text}
            </div>
          ))}
        </div>
      </details>

      {picking ? (
        <SocketPicker
          stationName={name}
          takenBy={takenBy}
          onCancel={() => setPicking(false)}
          onPick={(node) => {
            setPicking(false);
            station.assignSocket(node);
            syncPort();
          }}
        />
      ) : null}
      {prompt ? (
        <div className="modal-backdrop">
          <div className="card pad modal-card" {...modal.cardProps}>
            <h2 className="card-title">{prompt.label}</h2>
            <PromptInput secret={prompt.secret} onSubmit={answerPrompt} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** The one thing an operator reads from across the bench. */
const VERDICT: Record<SlotStatus, string> = {
  empty: "IDLE",
  ready: "IDLE",
  busy: "WORKING",
  pass: "PASS",
  fail: "FAIL",
  aborted: "ABORTED",
};

const PORT_TEXT: Record<PortState, string> = {
  none: "no socket assigned",
  empty: "socket empty",
  waiting: "device connected",
  working: "communicating",
  gone: "device disconnected",
};

const PORT_PILL: Record<PortState, string> = {
  none: "neutral",
  empty: "neutral",
  waiting: "ok",
  working: "warn",
  gone: "err",
};

/** A bar with no value renders empty rather than disappearing, so the layout
 *  does not jump every time a step starts or ends. */
function Bar({ label, pct }: { label: string; pct: number | null }) {
  return (
    <div className="bench-bar" title={`${label}: ${pct ?? 0}%`}>
      <div className="bench-bar-fill" style={{ width: `${pct ?? 0}%` }} />
    </div>
  );
}

function PromptInput({ secret, onSubmit }: { secret: boolean; onSubmit: (v: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="btn-row modal-actions">
      <input
        className="row-input mono"
        type={secret ? "password" : "text"}
        value={value}
        autoFocus
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSubmit(value);
        }}
      />
      <button type="button" className="btn" onClick={() => onSubmit("")}>
        Skip
      </button>
      <button type="button" className="btn btn-primary" onClick={() => onSubmit(value)}>
        OK
      </button>
    </div>
  );
}
