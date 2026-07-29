/** The operator bench: up to 5 station slots, each one USB adapter = one
 *  device. Chromium-only (Web Serial needs a secure context — localhost or
 *  HTTPS). The engine runs server-side; every line is stored as it arrives.
 *
 *  Two modes: a BATCH run (the batch's deployment version, published only) or
 *  a BENCH TRIAL (no batch, any version including a draft — recorded as such).
 */
import { useEffect, useMemo, useState } from "react";
import {
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
import { ErrorBanner } from "../components/Ui";
import { useStickyState } from "../useStickyState";

export default function FlashBench() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [deployments, setDeployments] = useState<DeploymentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("bench.project", null);
  const [mode, setMode] = useStickyState<"batch" | "trial">("bench.mode", "batch");
  const [runId, setRunId] = useStickyState<number | null>("bench.run", null);
  const [versionId, setVersionId] = useStickyState<number | null>("bench.versionv2", null);
  const [operator, setOperator] = useStickyState<string>("bench.operator", "");
  const [simPin, setSimPin] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [slots, setSlots] = useState(1);

  const webSerial = typeof navigator !== "undefined" && "serial" in navigator;

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

  const validRun = runs.some((r) => r.id === runId) ? runId : null;
  const chosenVersion = deployments
    .flatMap((d) => d.versions.map((v) => ({ d, v })))
    .find((x) => x.v.id === versionId);
  const trialIsDraft = mode === "trial" && chosenVersion?.v.status === "draft";

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Flash bench</h1>
          <span className="toolbar-total">
            one USB adapter per station · the engine stores every line as it arrives
          </span>
        </div>
        {!webSerial ? (
          <div className="banner-warn">
            This browser has no Web Serial — use Chrome or Edge on desktop, over localhost or HTTPS.
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
              }}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <select
              className="row-input"
              value={mode}
              title="a batch run uses the batch's published version; a bench trial can run a draft"
              onChange={(e) => setMode(e.target.value as "batch" | "trial")}
            >
              <option value="batch">batch run</option>
              <option value="trial">bench trial (no batch)</option>
            </select>
            {mode === "batch" ? (
              <select
                className="row-input"
                value={validRun ?? ""}
                title="production batch — the run belongs to it"
                onChange={(e) => setRunId(e.target.value === "" ? null : Number(e.target.value))}
              >
                <option value="">— pick the production batch —</option>
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>{r.label}</option>
                ))}
              </select>
            ) : null}
            <select
              className="row-input"
              value={versionId ?? ""}
              title={
                mode === "batch"
                  ? "leave empty to use the batch's assigned deployment version"
                  : "the version to try out — drafts are allowed here"
              }
              onChange={(e) => setVersionId(e.target.value === "" ? null : Number(e.target.value))}
            >
              <option value="">
                {mode === "batch" ? "batch's assigned version" : "— pick a version to try —"}
              </option>
              {versionOptions.map((group) => (
                <optgroup key={group.name} label={group.name}>
                  {group.versions.map((v) => (
                    <option key={v.id} value={v.id}>{v.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
            <input
              className="row-input"
              placeholder="operator"
              value={operator}
              onChange={(e) => setOperator(e.target.value)}
            />
            <input
              className="row-input mono"
              type="password"
              placeholder="SIM PIN (optional)"
              title="Used by the lte_sim_pin step. Empty = the param set default, else the engine prompts."
              value={simPin}
              onChange={(e) => setSimPin(e.target.value)}
            />
          </div>
          {mode === "batch" && versionId !== null ? (
            <input
              className="row-input override-reason"
              placeholder="override reason — why not the batch's assigned version?"
              value={overrideReason}
              onChange={(e) => setOverrideReason(e.target.value)}
            />
          ) : null}
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
          {Array.from({ length: slots }, (_, i) => (
            <BenchStation
              key={i}
              index={i}
              productionRunId={mode === "batch" ? validRun : null}
              deploymentVersionId={versionId}
              overrideReason={overrideReason}
              operator={operator}
              simPin={simPin}
            />
          ))}
        </div>
        <div className="btn-row">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setSlots((n) => Math.min(n + 1, 5))}
            disabled={slots >= 5}
          >
            + Station
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setSlots((n) => Math.max(n - 1, 1))}
            disabled={slots <= 1}
          >
            − Station
          </button>
        </div>
      </div>
    </div>
  );
}
