/** One programming run: the step timeline and the COMPLETE stored log —
 *  esptool output, every tx/rx console line, engine notes. Polls while the
 *  run is still going, so this page doubles as a live tail. */
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  errorMessage,
  getProgrammingLogs,
  getProgrammingRun,
  isAbortError,
  markRunAborted,
  type ProgrammingLogRow,
  type ProgrammingRunDetail,
} from "../api";
import { useDialog } from "../components/Dialog";
import { BackLink, ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import CheckGrid from "../components/flasher/CheckGrid";
import { fmtDuration, fmtWhen } from "../components/flasher/common";

const DIRS = ["", "tx", "rx", "app", "err", "esptool"];

export default function FlashRunDetail() {
  const { id } = useParams();
  const runId = Number(id);
  const dialog = useDialog();
  const [run, setRun] = useState<ProgrammingRunDetail | null>(null);
  const [logs, setLogs] = useState<ProgrammingLogRow[]>([]);
  const [dir, setDir] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const lastSeq = useRef(0);
  const logEnd = useRef<HTMLDivElement>(null);

  const loadRun = useCallback(() => {
    const ac = new AbortController();
    getProgrammingRun(runId, ac.signal)
      .then(setRun)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [runId]);

  useEffect(() => loadRun(), [loadRun]);

  // Full reload when the direction filter changes, incremental tail otherwise.
  useEffect(() => {
    lastSeq.current = 0;
    setLogs([]);
  }, [dir, runId]);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const rows = await getProgrammingLogs(runId, lastSeq.current, 3000, dir || undefined);
        if (stop) return;
        if (rows.length) {
          lastSeq.current = rows[rows.length - 1].seq;
          setLogs((old) => [...old, ...rows]);
        }
      } catch (err) {
        if (!isAbortError(err) && !stop) setError(errorMessage(err));
      }
    };
    void tick();
    const running = run?.status === "running";
    const timer = running ? setInterval(() => { void tick(); void loadRun(); }, 1500) : null;
    return () => {
      stop = true;
      if (timer) clearInterval(timer);
    };
  }, [runId, dir, run?.status, loadRun]);

  useEffect(() => {
    if (follow) logEnd.current?.scrollIntoView({ block: "end" });
  }, [logs, follow]);

  const abortZombie = async () => {
    if (!(await dialog.confirm("Mark this run aborted? Only for a run whose bench died.", {
      title: "Mark aborted", tone: "danger", confirmLabel: "Mark aborted",
    }))) return;
    try {
      await markRunAborted(runId);
      loadRun();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (error && !run) {
    return <div className="main-solo"><div className="page"><ErrorBanner message={error} /></div></div>;
  }
  if (!run) {
    return <div className="main-solo"><div className="page"><Spinner label="Loading run…" /></div></div>;
  }

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <BackLink to={run.device ? `/production/devices/${run.device.id}` : "/production/devices"}>
            ← {run.device ? (run.device.serial || run.device.mac) : "Devices"}
          </BackLink>
          <h1>Programming run #{run.id}</h1>
          <StatusPill status={run.status} />
          {run.status === "running" ? (
            <button type="button" className="btn btn-danger btn-sm" onClick={abortZombie}>
              Mark aborted
            </button>
          ) : null}
          <span className="toolbar-total">
            {run.deployment ? `${run.deployment.name} v${run.deployment.version_no}` : "?"} ·{" "}
            {run.production_run ? run.production_run.label : "?"} · {run.operator || "no operator"} ·{" "}
            {run.station || "?"} · {fmtWhen(run.started_at)} · {fmtDuration(run.duration_ms)}
          </span>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {run.error ? <div className="banner-error">{run.error}</div> : null}
        {run.release_override_reason ? (
          <div className="banner-warn">Script override: {run.release_override_reason}</div>
        ) : null}

        <div className="detail-page">
          <div className="detail-left">
            {run.checks?.length ? (
              <div className="card pad">
                <h2 className="card-title">What this run proved</h2>
                <CheckGrid checks={run.checks} />
              </div>
            ) : null}

            <div className="card pad">
              <h2 className="card-title">Steps</h2>
              <div className="table-wrap">
                <table className="data data-fixed progsteps-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Step</th>
                      <th>Op</th>
                      <th>Result</th>
                      <th className="num">Took</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.steps.map((s) => (
                      <tr key={s.idx} title={s.error ?? undefined}>
                        <td className="num">{s.idx + 1}</td>
                        <td title={s.label}>
                          {s.label || s.op}
                          {s.check ? <span className="muted dim mono"> {s.check}</span> : null}
                        </td>
                        <td className="mono dim">{s.op}</td>
                        <td><StatusPill status={s.status} /></td>
                        <td className="num">{fmtDuration(s.duration_ms)}</td>
                      </tr>
                    ))}
                    {run.steps.length === 0 ? (
                      <tr><td colSpan={5} className="empty">No steps recorded.</td></tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>
            {run.results && Object.keys(run.results).length ? (
              <div className="card pad">
                <h2 className="card-title">Captured results</h2>
                <table className="data data-fixed identity-table">
                  <tbody>
                    {Object.entries(run.results).map(([k, v]) => (
                      <tr key={k}>
                        <td className="muted">{k}</td>
                        <td className="mono" title={String(v)}>{String(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {run.params_snapshot && Object.keys(run.params_snapshot).length ? (
              <div className="card pad">
                <h2 className="card-title">Applied parameters</h2>
                <p className="card-subtitle">Secrets are masked in the snapshot itself.</p>
                <table className="data data-fixed identity-table">
                  <tbody>
                    {Object.entries(run.params_snapshot).map(([k, v]) => (
                      <tr key={k}>
                        <td className="muted">{k}</td>
                        <td className="mono" title={String(v)}>{String(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>

          <div className="detail-right">
            <div className="card pad">
              <div className="toolbar">
                <h2 className="card-title">Log</h2>
                <select className="row-input" value={dir} onChange={(e) => setDir(e.target.value)}>
                  {DIRS.map((d) => (
                    <option key={d} value={d}>{d === "" ? "all directions" : d}</option>
                  ))}
                </select>
                <label className="muted">
                  <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />{" "}
                  follow
                </label>
                <span className="toolbar-total">{logs.length} lines</span>
              </div>
              <div className="flash-log flash-log-tall mono">
                {logs.map((row) => (
                  <div key={row.seq} className={`fl-${row.dir}`} title={row.ts ?? ""}>
                    <span className="dim">{row.device_ts || (row.ts ?? "").slice(11, 19)}</span>{" "}
                    {row.dir === "tx" ? "→ " : row.dir === "rx" ? "← " : `[${row.dir}] `}
                    {row.text}
                  </div>
                ))}
                <div ref={logEnd} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
