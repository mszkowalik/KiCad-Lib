/** The operator bench: up to 5 station slots, each one USB adapter = one
 *  device. Chromium-only (Web Serial needs a secure context — localhost or
 *  HTTPS). The engine runs server-side; every line is stored as it arrives. */
import { useEffect, useMemo, useState } from "react";
import {
  errorMessage,
  getProjects,
  getRuns,
  isAbortError,
  listDeploymentScripts,
  type DeploymentScriptRow,
  type ProjectInfo,
  type RunInfo,
} from "../api";
import BenchStation from "../components/flasher/BenchStation";
import { ErrorBanner } from "../components/Ui";
import { useStickyState } from "../useStickyState";

export default function FlashBench() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [scripts, setScripts] = useState<DeploymentScriptRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("bench.project", null);
  const [runId, setRunId] = useStickyState<number | null>("bench.run", null);
  const [scriptVersionId, setScriptVersionId] = useStickyState<number | null>("bench.scriptv", null);
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
    Promise.all([getRuns(validProject, ac.signal), listDeploymentScripts(validProject, ac.signal)])
      .then(([r, s]) => {
        setRuns(r);
        setScripts(s);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [validProject]);

  const publishedVersions = useMemo(
    () =>
      scripts.flatMap((s) =>
        s.versions
          .filter((v) => v.status === "published")
          .map((v) => ({ id: v.id, label: `${s.name} v${v.version_no}` })),
      ),
    [scripts],
  );

  const validRun = runs.some((r) => r.id === runId) ? runId : null;

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
                setScriptVersionId(null);
              }}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <select
              className="row-input"
              value={validRun ?? ""}
              title="production batch — every programming run belongs to one"
              onChange={(e) => setRunId(e.target.value === "" ? null : Number(e.target.value))}
            >
              <option value="">— pick the production batch —</option>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>{r.label}</option>
              ))}
            </select>
            <select
              className="row-input"
              value={scriptVersionId ?? ""}
              title="deployment script version — leave on the batch default unless you know why"
              onChange={(e) => setScriptVersionId(e.target.value === "" ? null : Number(e.target.value))}
            >
              <option value="">batch's assigned script</option>
              {publishedVersions.map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
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
          {scriptVersionId !== null ? (
            <input
              className="row-input override-reason"
              placeholder="override reason — why not the batch's assigned script?"
              value={overrideReason}
              onChange={(e) => setOverrideReason(e.target.value)}
            />
          ) : null}
        </div>

        <div className="bench-grid">
          {Array.from({ length: slots }, (_, i) => (
            <BenchStation
              key={i}
              index={i}
              productionRunId={validRun}
              scriptVersionId={scriptVersionId}
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
