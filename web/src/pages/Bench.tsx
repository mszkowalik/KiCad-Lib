/** The bench: programming and marking on ONE page, driven by the batch's
 *  process (decision 0076).
 *
 *  ONE control decides what a run is: the batch. A batch's process lists the
 *  steps a bench does — Program and Test at the programming stations, Laser
 *  mark and Label at the marking station — each with the procedure that says
 *  how. The page offers exactly those steps, and the operator ticks the ones
 *  this bench does today: an operator programs, or marks and labels, and the
 *  page is laid out for that. "No batch" is a BENCH TRIAL — any procedure,
 *  drafts included, recorded as a trial.
 *
 *  There is ONE laser, so a selection that includes a marking step runs on one
 *  station and one device at a time. Programming alone uses up to four.
 *
 *  Browser-independent since decision 0023: every byte is the bench agent's,
 *  so this page needs no Web Serial, no port picker and no Chrome policy. The
 *  engine runs server-side; every line is stored as it arrives.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  benchAgentUrl,
  errorMessage,
  getRuns,
  getProjects,
  isAbortError,
  listDeployments,
  type DeploymentRow,
  type ProjectInfo,
  type RunInfo,
  getBenchStacks,
  setBenchStack,
  type BenchStacks,
  type BenchStep,
  getFlasherMeta,
  type FlasherMeta,
} from "../api";
import BenchStation, { type BenchSegment, type MarkOp } from "../components/flasher/BenchStation";
import {
  canProgram,
  listPrinters,
  MarkAgent,
  NEEDS_PROTOCOL,
  type AgentPrinter,
  type AgentRoll,
} from "../flasher/benchAgent";
import Field, { CheckField, FieldRow } from "../components/Field";
import { ErrorBanner } from "../components/Ui";
import { useStickyState } from "../useStickyState";

const MAX_STATIONS = 4;
const COUNT_KEY = "flasher.station-count.v1";

/** How often the bench asks after the laser and the printer while a marking
 *  step is selected: one HTTP request and one UDP PING. Programming alone asks
 *  only whether the agent is there, every ten seconds. */
const MACHINE_POLL_MS = 2000;
const AGENT_POLL_MS = 10_000;

/** How many programming stations this bench uses. One by default — a new
 *  operator has one cable in their hand, not four. */
function readStationCount(): number {
  try {
    const n = Number(localStorage.getItem(COUNT_KEY));
    return Number.isInteger(n) && n >= 1 && n <= MAX_STATIONS ? n : 1;
  } catch {
    return 1;
  }
}

function writeStationCount(n: number): number {
  try {
    localStorage.setItem(COUNT_KEY, String(n));
  } catch {
    /* blocked storage: the count still works for this session */
  }
  return n;
}

const MARK_OP_OF: Record<string, MarkOp | undefined> = { mark_laser: "mark_laser", label: "print_label" };

type AgentState =
  | { kind: "checking" }
  | { kind: "down"; error: string }
  | {
      kind: "up";
      /** this agent carries no esptool, so it cannot program */
      cannotProgram: boolean;
      /** this agent is too old to print; it still marks */
      cannotPrint: boolean;
      /** the machines, asked only while a marking step is selected */
      lightburn: boolean;
      busy: boolean | null;
      laserUsb: { present: boolean; name: string; ids: string } | null;
      host: string;
      printers: AgentPrinter[];
      rolls: AgentRoll[];
    };

/** The agent, watched: whether it is there, and while a marking step is
 *  selected, the laser and the printers. Sequential rather than an interval,
 *  so a slow answer never piles checks up, and paused while the tab is
 *  hidden. */
function useBenchAgent(watchMachines: boolean): { state: AgentState; checkedAt: string | null } {
  const [state, setState] = useState<AgentState>({ kind: "checking" });
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const check = useCallback(async () => {
    const a = new MarkAgent();
    try {
      const hello = await a.hello();
      let lightburn = false;
      let busy: boolean | null = null;
      let laserUsb: { present: boolean; name: string; ids: string } | null = null;
      let printers: AgentPrinter[] = [];
      let rolls: AgentRoll[] = [];
      if (watchMachines) {
        const health = await a.health();
        lightburn = health.responsive;
        busy = health.busy;
        laserUsb = health.laserUsb;
        try {
          const got = await listPrinters();
          printers = got.printers;
          rolls = got.rolls;
        } catch {
          // An agent from before labels existed answers 404 here; it still marks.
        }
      }
      setState({
        kind: "up",
        cannotProgram: !canProgram(hello),
        cannotPrint: (hello.protocol ?? 0) < NEEDS_PROTOCOL,
        lightburn,
        busy,
        laserUsb,
        host: hello.lightburn_host,
        printers,
        rolls,
      });
    } catch (e) {
      setState({ kind: "down", error: errorMessage(e) });
    } finally {
      setCheckedAt(new Date().toLocaleTimeString());
      a.close();
    }
  }, [watchMachines]);

  useEffect(() => {
    let alive = true;
    let timer = 0;
    const every = watchMachines ? MACHINE_POLL_MS : AGENT_POLL_MS;
    const tick = async () => {
      if (!alive) return;
      try {
        if (document.visibilityState === "visible") await check();
      } finally {
        // ALWAYS re-arm: a throw must not end the watch for good.
        if (alive) timer = window.setTimeout(tick, every);
      }
    };
    // Coming back to the tab must not wait for a throttled timer.
    const wake = () => {
      if (document.visibilityState !== "visible") return;
      clearTimeout(timer);
      void tick();
    };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("focus", wake);
    void tick();
    return () => {
      alive = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("focus", wake);
    };
  }, [check, watchMachines]);
  return { state, checkedAt };
}

export default function Bench() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  /** Which project `runs` belongs to: an empty list cannot say whether it is
   *  "no batches" or "not loaded yet". */
  const [runsFor, setRunsFor] = useState<number | null>(null);
  const [deployments, setDeployments] = useState<DeploymentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("bench.project", null);
  /** No batch = a bench trial. Defaulted to the project's latest batch each
   *  time the project is chosen (user decision 2026-09-17). */
  const [runId, setRunId] = useState<number | null>(null);
  /** The procedure a TRIAL runs. A batch runs what its process names. */
  const [trialVersionId, setTrialVersionId] = useStickyState<number | null>("bench.versionv2", null);
  const [simPin, setSimPin] = useState("");
  const [autoStart, setAutoStart] = useStickyState<boolean>("bench.autostart", false);
  const [slots, setSlots] = useState(readStationCount);
  const [meta, setMeta] = useState<FlasherMeta | null>(null);
  /** Another version than a procedure's current one, by deployment, and why. */
  const [pickedVersion, setPickedVersion] = useState<Record<number, number>>({});
  const [overrideReason, setOverrideReason] = useState("");

  useEffect(() => {
    const ac = new AbortController();
    getFlasherMeta(ac.signal).then(setMeta).catch(() => setMeta(null));
    // Every company's projects, whatever the header switcher shows: the bench
    // works on whichever company's devices are on the table.
    getProjects(ac.signal, "all")
      .then(setProjects)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  const validProject = projects.some((p) => p.id === projectId) ? projectId : projects[0]?.id ?? null;

  useEffect(() => {
    if (!validProject) return;
    const ac = new AbortController();
    Promise.all([getRuns(validProject, ac.signal, "all"), listDeployments(validProject, ac.signal)])
      .then(([r, d]) => {
        setRuns(r);
        setRunsFor(validProject);
        setDeployments(d);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [validProject]);

  /** The project's LATEST batch: newest run date, then newest id. */
  const latestRunId = useMemo(() => {
    const sorted = [...runs].sort((a, b) =>
      (b.run_date || "").localeCompare(a.run_date || "") || b.id - a.id);
    return sorted[0]?.id ?? null;
  }, [runs]);
  // Applied ONCE per project, so clearing the batch by hand stays cleared.
  const batchDefaultedFor = useRef<number | null>(null);
  useEffect(() => {
    if (!validProject || runsFor !== validProject) return;
    if (batchDefaultedFor.current === validProject) return;
    batchDefaultedFor.current = validProject;
    setRunId(latestRunId);
  }, [validProject, runsFor, latestRunId]);

  const validRun = runs.some((r) => r.id === runId) ? runId : null;
  const batch = runs.find((r) => r.id === validRun) ?? null;
  const trial = validRun === null;

  /** The batch's process: its bench steps, and its stacks (decision 0059 §7:
   *  each board programmed takes one unit of the selected stack). */
  const [stacks, setStacks] = useState<BenchStacks | null>(null);
  const [lotError, setLotError] = useState<string | null>(null);
  useEffect(() => {
    setStacks(null);
    setPickedVersion({});
    setOverrideReason("");
    if (validRun === null) return;
    const ac = new AbortController();
    const load = () => getBenchStacks(validRun, ac.signal).then(setStacks).catch(() => undefined);
    void load();
    // The bench names a twin per board, so the counts fall while it works.
    const timer = window.setInterval(load, 15000);
    return () => { ac.abort(); window.clearInterval(timer); };
  }, [validRun]);
  const pickStack = (value: string) => {
    if (validRun === null) return;
    setLotError(null);
    setBenchStack(validRun, value || null)
      .then(() => getBenchStacks(validRun))
      .then(setStacks)
      .catch((err) => setLotError(errorMessage(err)));
  };

  const steps: BenchStep[] = useMemo(() => stacks?.steps ?? [], [stacks]);
  /** The steps this bench does today, by key, remembered per project: an
   *  operator programs all day, or marks and labels all day. */
  const [chosenKeys, setChosenKeys] = useStickyState<Record<string, string[]>>("bench.steps", {});
  const runnable = (s: BenchStep) => Boolean(s.deployment?.current_version_id);
  const selectedKeys = useMemo(() => {
    const stored = chosenKeys[String(validProject)];
    // Unticking the last step is a choice too: the default is only for a
    // project nothing was chosen for yet — its programming steps, else its
    // marking ones.
    if (stored !== undefined) return stored.filter((k) => steps.some((s) => s.key === k && runnable(s)));
    const prog = steps.filter((s) => s.place === "programming_bench" && runnable(s));
    return (prog.length ? prog : steps.filter(runnable)).map((s) => s.key);
  }, [chosenKeys, validProject, steps]);
  const toggleStep = (key: string, on: boolean) => {
    const next = on ? [...selectedKeys, key] : selectedKeys.filter((k) => k !== key);
    setChosenKeys({ ...chosenKeys, [String(validProject)]: next });
  };

  const versionsOf = (depId: number) => deployments.find((d) => d.id === depId)?.versions ?? [];
  const versionLabel = (depId: number, vid: number | null | undefined) => {
    const v = versionsOf(depId).find((x) => x.id === vid);
    return v ? `v${v.version_no}` : "—";
  };

  /** The selected steps as runs, in route order. Consecutive marking steps
   *  that name one procedure are ONE run of it, doing both actions. */
  const segments: BenchSegment[] = useMemo(() => {
    if (trial) {
      const d = deployments.find((x) => x.versions.some((v) => v.id === trialVersionId));
      if (!d || !trialVersionId) return [];
      return [{
        versionId: trialVersionId,
        label: d.kind === "mark" ? "Mark + label" : d.name,
        markOps: d.kind === "mark" ? ["mark_laser", "print_label"] : [],
      }];
    }
    const out: BenchSegment[] = [];
    for (const s of steps) {
      if (!selectedKeys.includes(s.key) || !s.deployment || !runnable(s)) continue;
      const vid = pickedVersion[s.deployment.id] ?? s.deployment.current_version_id!;
      const op = MARK_OP_OF[s.kind];
      const last = out[out.length - 1];
      if (op && last && last.versionId === vid && last.markOps.length) {
        last.markOps = [...last.markOps, op];
        last.label = `${last.label} + ${s.label}`;
      } else {
        out.push({ versionId: vid, label: s.label, markOps: op ? [op] : [] });
      }
    }
    return out;
  }, [trial, deployments, trialVersionId, steps, selectedKeys, pickedVersion]);

  const marking = segments.some((s) => s.markOps.length > 0);
  const { state: agent, checkedAt } = useBenchAgent(marking);

  /** A step run at another version than its procedure's current one. */
  const overridden = !trial && steps.some((s) =>
    selectedKeys.includes(s.key) && s.deployment && pickedVersion[s.deployment.id] !== undefined
    && pickedVersion[s.deployment.id] !== s.deployment.current_version_id);
  /** The procedures the selected steps use, once each, for "Versions…". */
  const usedDeps = useMemo(() => {
    const seen = new Map<number, { id: number; name: string; current: number | null }>();
    for (const s of steps) {
      if (selectedKeys.includes(s.key) && s.deployment && !seen.has(s.deployment.id))
        seen.set(s.deployment.id, { id: s.deployment.id, name: s.deployment.name,
                                    current: s.deployment.current_version_id });
    }
    return [...seen.values()];
  }, [steps, selectedKeys]);

  const allVersions = deployments.flatMap((d) => d.versions.map((v) => ({ d, v })));
  const trialChosen = allVersions.find((x) => x.v.id === trialVersionId);
  const trialIsDraft = trial && trialChosen?.v.status === "draft";
  /** The SIM PIN box belongs to a procedure with an `lte_sim_pin` step. */
  const wantsSimPin = segments.some((seg) => allVersions.find((x) => x.v.id === seg.versionId)?.v.needs_sim_pin);

  const stationCount = marking ? 1 : slots;
  const agentUp = agent.kind === "up";

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Bench</h1>
          <span className="toolbar-total">
            the batch's process says what this bench can do · the engine stores every line as it arrives
          </span>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {lotError ? <ErrorBanner message={lotError} /> : null}
        {agent.kind === "up" && agent.cannotProgram && segments.some((s) => !s.markOps.length) ? (
          <div className="banner-error">
            <strong>This machine is running an old bench agent.</strong> It cannot program — it has no
            esptool inside it. Download it again below, replace the copy in Applications, and restart it.
          </div>
        ) : null}

        <div className="card pad stack">
          <FieldRow>
            <Field label="Project">
              <select
                className="text"
                value={validProject ?? ""}
                onChange={(e) => {
                  setProjectId(Number(e.target.value));
                  setRunId(null);
                  // Picking a project asks for its latest batch back.
                  batchDefaultedFor.current = null;
                }}
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </Field>
            <Field label="Batch">
              <select
                className="text"
                value={validRun ?? ""}
                title="The batch this run belongs to. None = a bench trial: any procedure, drafts included, recorded as a trial."
                onChange={(e) => setRunId(e.target.value === "" ? null : Number(e.target.value))}
              >
                <option value="">no batch — bench trial</option>
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>{r.label}</option>
                ))}
              </select>
            </Field>
            {stacks?.crafted && steps.some((s) => s.kind === "program" && selectedKeys.includes(s.key)) ? (
              <Field label="Boards from">
                <select
                  className="text"
                  value={stacks.selected ?? ""}
                  title="The stack these boards come from. Each board programmed takes one unit of it; when it is used up the bench asks for the next."
                  onChange={(e) => pickStack(e.target.value)}
                >
                  <option value="">no stack — boards become gaps</option>
                  {stacks.selected && !stacks.stacks.some((s) => s.stack === stacks.selected) ? (
                    <option value={stacks.selected}>selected stack (used up)</option>
                  ) : null}
                  {stacks.stacks.map((s) => (
                    <option key={s.stack} value={s.stack}>
                      {s.run_label}: {s.done.join(" + ")} — {s.count} left
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
            {trial ? (
              <Field label="Procedure to try">
                <select
                  className="text"
                  value={trialVersionId ?? ""}
                  onChange={(e) => setTrialVersionId(e.target.value === "" ? null : Number(e.target.value))}
                >
                  <option value="">— pick a version to try —</option>
                  {deployments.map((d) => (
                    <optgroup key={d.id} label={`${d.name} (${d.kind})`}>
                      {d.versions.map((v) => (
                        <option key={v.id} value={v.id}>
                          v{v.version_no} ({v.status})
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </Field>
            ) : null}
            {wantsSimPin ? (
              <Field label="SIM PIN">
                <input
                  className="text mono"
                  type="password"
                  placeholder="optional"
                  title="Used by the lte_sim_pin step. Empty = the param set default, else the engine prompts."
                  value={simPin}
                  onChange={(e) => setSimPin(e.target.value)}
                />
              </Field>
            ) : null}
          </FieldRow>

          {!trial && batch && stacks && !stacks.crafted ? (
            <p className="banner-warn">
              {batch.label} has no process yet, so this bench cannot tell what to do with its devices.
              Give it one on <Link to={`/runs/${batch.id}?tab=process`}>the batch's Process tab</Link>, or
              run a bench trial.
            </p>
          ) : null}
          {!trial && stacks?.crafted && !steps.length ? (
            <p className="banner-warn">
              The process of {batch?.label} has no step a bench does. Add Program, Test, Laser mark or
              Label to it on <Link to={`/runs/${validRun}?tab=process`}>the batch's Process tab</Link>.
            </p>
          ) : null}

          {/* The process's bench steps, in its order. The operator ticks what
              this bench does today; a step whose process names no procedure is
              shown and cannot be ticked, with the reason. */}
          {!trial && steps.length ? (
            <div className="stack">
              <span className="muted">Steps this bench does</span>
              <div className="btn-row">
                {steps.map((s) => (
                  <CheckField
                    key={s.key}
                    checked={selectedKeys.includes(s.key)}
                    onChange={(on) => toggleStep(s.key, on)}
                    disabled={!runnable(s)}
                    title={
                      !s.deployment
                        ? "The process names no procedure for this step — set one on the batch's Process tab"
                        : !s.deployment.current_version_id
                          ? `${s.deployment.name} has no published version`
                          : `${s.deployment.name} ${versionLabel(s.deployment.id, pickedVersion[s.deployment.id] ?? s.deployment.current_version_id)}`
                    }
                  >
                    {s.label}
                    {s.deployment && runnable(s) ? (
                      <span className="muted dim">
                        {" "}· {s.deployment.name}{" "}
                        {versionLabel(s.deployment.id, pickedVersion[s.deployment.id] ?? s.deployment.current_version_id)}
                      </span>
                    ) : (
                      <span className="muted dim"> · no procedure</span>
                    )}
                  </CheckField>
                ))}
              </div>
              {usedDeps.length ? (
                <details>
                  <summary className="muted">Versions…</summary>
                  <FieldRow>
                    {usedDeps.map((d) => (
                      <Field key={d.id} label={d.name}>
                        <select
                          className="text"
                          value={pickedVersion[d.id] ?? d.current ?? ""}
                          onChange={(e) => {
                            const vid = Number(e.target.value);
                            const next = { ...pickedVersion };
                            if (vid === d.current) delete next[d.id];
                            else next[d.id] = vid;
                            setPickedVersion(next);
                          }}
                        >
                          {versionsOf(d.id).filter((v) => v.status === "published").map((v) => (
                            <option key={v.id} value={v.id}>
                              v{v.version_no}{v.id === d.current ? " (current)" : ""}
                            </option>
                          ))}
                        </select>
                      </Field>
                    ))}
                  </FieldRow>
                  {overridden ? (
                    <Field label="Why not the current version?" hint="Required — it goes in each run's record.">
                      <input
                        className="text"
                        value={overrideReason}
                        onChange={(e) => setOverrideReason(e.target.value)}
                      />
                    </Field>
                  ) : null}
                </details>
              ) : null}
            </div>
          ) : null}

          <CheckField
            checked={autoStart}
            onChange={setAutoStart}
            title="Each station runs the selected steps the moment a device appears on its socket, once per device. A marking run also waits for the device's serial and for the machines it needs."
          >
            Run the selected steps automatically when a device is plugged in
          </CheckField>
          {trialIsDraft ? (
            <p className="banner-warn">
              Trying a DRAFT version. Each run is marked as a draft run and cannot be counted as batch
              production.
            </p>
          ) : null}

          <AgentStrip state={agent} checkedAt={checkedAt} marking={marking} />
        </div>

        <div className={`bench-grid${marking ? " bench-grid-one" : ""}`}>
          {Array.from({ length: marking ? 1 : MAX_STATIONS }, (_, i) =>
            i < stationCount ? (
              <BenchStation
                key={`${marking ? "mark" : "prog"}-${i}`}
                index={i}
                layout={marking ? "mark" : "program"}
                segments={segments}
                productionRunId={validRun}
                autoStart={autoStart}
                overrideReason={overridden ? overrideReason : ""}
                // A hidden box must not still be sending a value.
                simPin={wantsSimPin ? simPin : ""}
                projectId={validProject}
                meta={meta}
                agentUp={agentUp}
                laser={
                  agent.kind === "up"
                    ? { responsive: agent.lightburn, busy: agent.busy, laserUsb: agent.laserUsb }
                    : { responsive: false, busy: null, laserUsb: null }
                }
                printers={agent.kind === "up" ? agent.printers : []}
                rolls={agent.kind === "up" ? agent.rolls : []}
              />
            ) : (
              <div key={i} className="bench-empty" />
            ),
          )}
        </div>
        {marking ? null : (
          <div className="btn-row">
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setSlots((n) => writeStationCount(Math.min(n + 1, MAX_STATIONS)))}
              disabled={slots >= MAX_STATIONS}
            >
              + Station
            </button>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setSlots((n) => writeStationCount(Math.max(n - 1, 1)))}
              disabled={slots <= 1}
            >
              − Station
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/** The bench agent in ONE line: whether it runs, and while a marking step is
 *  selected, whether it reaches LightBurn and a printer. Watched, not asked
 *  for, so it carries no button but the download. */
function AgentStrip({ state, checkedAt, marking }: {
  state: AgentState; checkedAt: string | null; marking: boolean;
}) {
  const [pill, tone, note] =
    state.kind === "checking"
      ? ["checking…", "neutral", ""]
      : state.kind === "down"
        ? [
            "not running",
            "err",
            "It does all the serial work, so nothing can run until it is started. Download it, open " +
              "the zip and double-click 7Sigma Agent. If it is running, allow local network access when " +
              "Chrome asks.",
          ]
        : marking && state.cannotPrint
          ? ["out of date", "warn", "This agent marks but cannot print labels. Download it again."]
          : [
              "running",
              "ok",
              marking
                ? `Driving LightBurn at ${state.host}` +
                  (state.printers.length
                    ? ` and ${state.printers.length} printer(s) on this machine.`
                    : ". It reports no printer on this machine.")
                : "",
            ];
  return (
    <div className="bench-agent">
      <strong>Bench agent</strong>
      <span className={`pill ${tone}`}>{pill}</span>
      {note ? <span className="muted bench-agent-note">{note}</span> : null}
      {checkedAt ? <span className="muted dim">{checkedAt}</span> : null}
      {/* Always offered: the agent is set up BEFORE anything is wrong. */}
      <a className="btn btn-sm" href={benchAgentUrl()} download>
        Download the bench agent
      </a>
    </div>
  );
}
