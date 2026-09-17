/** The operator bench: FOUR station slots, each one USB socket = one device.
 *
 *  Browser-independent since decision 0023: every byte is the bench agent's, so
 *  this page needs no Web Serial, no port picker and no Chrome policy. The
 *  engine runs server-side; every line is stored as it arrives.
 *
 *  ONE control decides what a run is: the batch it belongs to. "no batch" is a
 *  BENCH TRIAL — any version including a draft, recorded as a trial. Picking a
 *  batch makes it production, on that batch's assigned version unless the
 *  operator names another and says why.
 */
import { useEffect, useMemo, useRef, useState } from "react";
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
} from "../api";
import BenchStation from "../components/flasher/BenchStation";
import { MarkAgent } from "../flasher/benchAgent";
import { CheckField } from "../components/Field";
import { ErrorBanner } from "../components/Ui";
import { useStickyState } from "../useStickyState";

const MAX_STATIONS = 4;
const COUNT_KEY = "flasher.station-count.v1";

/** How many stations this bench uses. One by default — a new operator has one
 *  cable in their hand, not four. */
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

export default function FlashBench() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [deployments, setDeployments] = useState<DeploymentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("bench.project", null);
  /** No batch picked = a bench trial. The mode used to be its own dropdown
   *  beside the batch one, which made "batch run" with no batch a state the
   *  page had to warn about; now the two are one control and that state cannot
   *  be expressed (user decision 2026-09-17). */
  // The batch is deliberately NOT remembered (user decision 2026-09-16). A
  // remembered batch is the one an operator programs a tray into by accident
  // the next morning; picking it is one click and it has to be a decision.
  const [runId, setRunId] = useState<number | null>(null);
  const [versionId, setVersionId] = useStickyState<number | null>("bench.versionv2", null);
  const [simPin, setSimPin] = useState("");
  // A heartbeat to the bench agent: it does every byte of serial work, so
  // "is it running" is the first thing this page has to be able to say. It
  // also tells the agent's own window that a bench page is here.
  const [agentUp, setAgentUp] = useState<boolean | null>(null);
  useEffect(() => {
    const a = new MarkAgent();
    let alive = true;
    const beat = async () => {
      try {
        await a.hello();
        if (alive) setAgentUp(true);
      } catch {
        if (alive) setAgentUp(false);
      }
    };
    void beat();
    const timer = window.setInterval(() => void beat(), 10_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);
  const [overrideReason, setOverrideReason] = useState("");
  // OFF by default, on purpose: a programming run erases the device and writes
  // firmware, so arming a bench to do that on plug-in is a decision somebody
  // makes, not a state they find the page in. Remembered per browser once made.
  const [autoStart, setAutoStart] = useStickyState<boolean>("bench.autostart", false);
  // How many stations are in use, 1..4, remembered across reloads. The GRID is
  // always four cells wide: removing a station leaves its place empty rather
  // than letting the remaining ones spread out, so a station never moves under
  // the operator's hand mid-batch.
  const [slots, setSlots] = useState(readStationCount);

  useEffect(() => {
    const ac = new AbortController();
    getProjects(ac.signal)
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
    Promise.all([getRuns(validProject, ac.signal), listDeployments(validProject, ac.signal)])
      .then(([r, d]) => {
        setRuns(r);
        setDeployments(d);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [validProject]);

  /** Every version, grouped by deployment, with channel and status labels. */
  const versionOptions = useMemo(
    () =>
      deployments.map((d) => ({
        name: d.name,
        versions: d.versions.map((v) => {
          const chans = d.channels.filter((c) => c.deployment_version_id === v.id).map((c) => c.name);
          const tags = [v.status, ...chans].join(", ");
          return { id: v.id, label: `v${v.version_no} (${tags})`, status: v.status };
        }),
      })),
    [deployments],
  );

  /** The project's CONFIG procedure — `kind: "flash"`, read from the kind and
   *  never from the name, the same rule the Test button follows. Its current
   *  version is what the bench starts on: it is what a batch is programmed
   *  with all day, and an empty dropdown made every session begin with the
   *  same click. */
  const configVersionId = useMemo(
    () => deployments.find((d) => d.kind === "flash")?.current_version_id ?? null,
    [deployments],
  );

  // Applied ONCE per project, so choosing "batch's assigned version" by hand
  // afterwards sticks instead of snapping back. A version remembered from an
  // earlier session wins when it still belongs to this project.
  const defaultedFor = useRef<number | null>(null);
  useEffect(() => {
    // Wait for THIS project's deployments: switching project leaves the
    // previous list in state for a moment, and defaulting from it marked the
    // project done and left the box empty.
    if (!validProject || deployments[0]?.project_id !== validProject) return;
    if (defaultedFor.current === validProject) return;
    defaultedFor.current = validProject;
    const known = deployments.some((d) => d.versions.some((v) => v.id === versionId));
    if (!known) setVersionId(configVersionId);
  }, [validProject, deployments, configVersionId, versionId, setVersionId]);

  const validRun = runs.some((r) => r.id === runId) ? runId : null;
  const batch = runs.find((r) => r.id === validRun) ?? null;
  /** A run with no batch is a bench trial: it may run a draft, and it is
   *  recorded as a trial rather than counted as batch production. */
  const trial = validRun === null;

  /** The version the BATCH says to use: its pinned one, else the version its
   *  channel points at. Null for every batch today — none pins or follows
   *  anything — which is why the operator's pick is not an override. */
  const assignedVersionId = useMemo(() => {
    if (!batch) return null;
    if (batch.deployment_version_id) return batch.deployment_version_id;
    const name = batch.deployment_channel;
    if (!name) return null;
    for (const d of deployments) {
      const chan = d.channels.find((c) => c.name === name);
      if (chan) return chan.deployment_version_id;
    }
    return null;
  }, [batch, deployments]);

  const isOverride =
    !trial && versionId !== null && assignedVersionId !== null
    && versionId !== assignedVersionId;

  const chosenVersion = deployments
    .flatMap((d) => d.versions.map((v) => ({ d, v })))
    .find((x) => x.v.id === versionId);
  const trialIsDraft = trial && chosenVersion?.v.status === "draft";

  /** The SIM PIN box belongs to the PROCEDURE, not to the bench. Only a
   *  procedure with an `lte_sim_pin` step can use the value (Dongle_V3
   *  today); on a Dongle_V2 or an Aqua the box asked for a secret that had
   *  nowhere to go. In batch mode the version is the batch's own, and the page
   *  does not resolve it, so the question falls back to the project: does any
   *  of its procedures ask for a PIN? */
  const wantsSimPin = useMemo(
    () =>
      chosenVersion
        ? chosenVersion.v.needs_sim_pin
        : deployments.some((d) => d.versions.some((v) => v.needs_sim_pin)),
    [chosenVersion, deployments],
  );

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Flash bench</h1>
          <span className="toolbar-total">
            one USB adapter per station · the engine stores every line as it arrives
          </span>
        </div>
        {agentUp === false ? (
          <div className="banner-warn">
            The bench agent is not running on this machine. It does all the serial work, so
            nothing can be programmed until it is started.
          </div>
        ) : null}
        {error ? <ErrorBanner message={error} /> : null}

        <div className="card pad">
          <div className="btn-row">
            <select
              className="row-input"
              value={validProject ?? ""}
              onChange={(e) => {
                setProjectId(Number(e.target.value));
                setRunId(null);
                setVersionId(null);
                // Picking a project — even the same one again — asks for its
                // default back. Only this control clears the mark, so a
                // deliberate "batch's assigned version" still sticks.
                defaultedFor.current = null;
              }}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <select
              className="row-input"
              value={validRun ?? ""}
              title="The batch this run belongs to. None = a bench trial: it may run a draft, and it is recorded as a trial rather than counted as production."
              onChange={(e) => setRunId(e.target.value === "" ? null : Number(e.target.value))}
            >
              <option value="">no batch — bench trial</option>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>{r.label}</option>
              ))}
            </select>
            <select
              className="row-input"
              value={versionId ?? ""}
              title={
                trial
                  ? "the version to try out — drafts are allowed on a bench trial"
                  : "leave empty to use the batch's assigned deployment version"
              }
              onChange={(e) => setVersionId(e.target.value === "" ? null : Number(e.target.value))}
            >
              <option value="">
                {trial ? "— pick a version to try —" : "batch's assigned version"}
              </option>
              {versionOptions.map((group) => (
                <optgroup key={group.name} label={group.name}>
                  {group.versions.map((v) => (
                    <option key={v.id} value={v.id}>{v.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
            {wantsSimPin ? (
              <input
                className="row-input mono"
                type="password"
                placeholder="SIM PIN (optional)"
                title="Used by the lte_sim_pin step. Empty = the param set default, else the engine prompts."
                value={simPin}
                onChange={(e) => setSimPin(e.target.value)}
              />
            ) : null}
          </div>
          {isOverride ? (
            <input
              className="row-input override-reason"
              placeholder="override reason — why not the batch's assigned version?"
              value={overrideReason}
              onChange={(e) => setOverrideReason(e.target.value)}
            />
          ) : null}
          <CheckField
            checked={autoStart}
            onChange={setAutoStart}
            title="Each station starts its own run the moment a device appears on its port. Armed once per device: a finished unit left plugged in is not programmed twice."
          >
            Program automatically when a device is plugged in
          </CheckField>
          {trialIsDraft ? (
            <p className="banner-warn">
              Trying a DRAFT version. Each run is marked as a draft run and cannot be counted as
              batch production.
            </p>
          ) : null}
          {chosenVersion ? (
            <p className="muted">
              {chosenVersion.d.name} v{chosenVersion.v.version_no} · {chosenVersion.v.image_count}{" "}
              image(s) · {chosenVersion.v.file_count} berryware files
              {chosenVersion.v.files_label ? ` (${chosenVersion.v.files_label})` : ""} ·{" "}
              {chosenVersion.v.step_count} steps
            </p>
          ) : null}
        </div>

        <div className="bench-grid">
          {Array.from({ length: MAX_STATIONS }, (_, i) =>
            i < slots ? (
              <BenchStation
                key={i}
                index={i}
                productionRunId={validRun}
                deploymentVersionId={versionId}
                autoStart={autoStart}
                overrideReason={overrideReason}
                // A hidden box must not still be sending a value: switching
                // from a V3 to a V2 would carry the PIN into a run that has
                // no step to consume it.
                simPin={wantsSimPin ? simPin : ""}
                projectId={validProject}
              />
            ) : (
              <div key={i} className="bench-empty" />
            ),
          )}
        </div>
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
        <BenchSetupHint agentUp={agentUp} />
      </div>
    </div>
  );
}

/** One-time bench setup, offered rather than required.
 *
 *  Two different things, and the agent now covers both. A station is bound to a
 *  physical USB SOCKET, which a page cannot see — Web Serial gives it a vendor
 *  and product id and nothing else, and every V2 dongle shares those. And the
 *  port picker reappears for every unit, because a CH340 reports no USB serial
 *  number for Chrome to remember a permission by. The agent answers the first
 *  and grants the second, so it is one download rather than two.
 */
function BenchSetupHint({ agentUp }: { agentUp: boolean | null }) {
  const mac = typeof navigator !== "undefined" && /Mac/i.test(navigator.userAgent);
  return (
    <p className="muted">
      {agentUp === true ? (
        <strong>Bench agent: running on this machine.</strong>
      ) : agentUp === false ? (
        <strong>Bench agent: not running on this machine.</strong>
      ) : null}{" "}
      The bench agent does all the serial work — esptool and the device console — so this
      browser never opens a port.{" "}
      {mac ? (
        <>
          <a href={benchAgentUrl()} download>
            Download the bench agent
          </a>
          , expand the zip and open <strong>7Sigma Agent</strong>, then give each station a socket.
          Nothing else is needed: no port picker, no serial permission, no Chrome setting.
        </>
      ) : (
        <>The agent is macOS only so far, so this system cannot program from the bench yet.</>
      )}
    </p>
  );
}
