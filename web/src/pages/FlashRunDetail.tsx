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
  type ProgrammingStepRow,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import FoldSection, { StatChip } from "../components/FoldSection";
import { CheckField } from "../components/Field";
import { useDialog } from "../components/Dialog";
import { BackLink, ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import CheckGrid from "../components/flasher/CheckGrid";
import { fmtDuration } from "../components/flasher/common";
import { localWhen, localTime } from "../format";

const DIRS = ["", "tx", "rx", "app", "err", "esptool"];

/** The loudest step state first: a fold never hides a problem. */
function stepRank(status: string): number {
  if (status === "fail" || status === "error" || status === "failed") return 0;
  return status === "aborted" || status === "running" ? 1 : 2;
}

/* Sorted by its own number first, because the order of the steps is what happened.
   A failed step's error is on the hover of its Step and Result cells. The card sits
   in the narrow column, where a filter box needs 76 px with its cell, so only Step
   and Result take one. A pill and a duration may not be cut; a label may. */
const STEP_COLS: Column<ProgrammingStepRow>[] = [
  {
    key: "idx",
    label: "#",
    width: 12,
    numeric: true,
    interactive: false,
    sortable: true,
    get: (s) => s.idx + 1,
  },
  {
    key: "step",
    label: "Step",
    width: 27,
    get: (s) => `${s.label || s.op} ${s.check ?? ""}`.trim(),
    title: (s) => s.error ?? s.label,
    render: (s) => (
      <>
        {s.label || s.op}
        {s.check ? <span className="muted dim mono"> {s.check}</span> : null}
      </>
    ),
  },
  { key: "op", label: "Op", width: 17, className: "mono dim", interactive: false, sortable: true, get: (s) => s.op },
  {
    key: "result",
    label: "Result",
    width: 24,
    get: (s) => s.status,
    title: (s) => s.error ?? s.status,
    render: (s) => <StatusPill status={s.status} />,
  },
  {
    key: "took",
    label: "Took",
    width: 20,
    numeric: true,
    interactive: false,
    sortable: true,
    get: (s) => s.duration_ms ?? "",
    render: (s) => fmtDuration(s.duration_ms),
  },
];

/** Named values of one run: what it captured, or what it was given. */
function RunValues({ values }: { values: Record<string, unknown> }) {
  return (
    <table className="data data-fixed identity-table">
      <tbody>
        {Object.entries(values).map(([k, v]) => (
          <tr key={k}>
            <td className="muted">{k}</td>
            <td className="mono" title={String(v)}>{String(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

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
  const logBox = useRef<HTMLDivElement>(null);

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
    // The box and nothing else. `scrollIntoView` also moves every ancestor, and
    // it pushed the whole `overflow: hidden` page sideways.
    if (follow && logBox.current) logBox.current.scrollTop = logBox.current.scrollHeight;
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
            {run.station || "?"} · {localWhen(run.started_at)} · {fmtDuration(run.duration_ms)}
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

            <FoldSection
              title="Steps"
              count={run.steps.length}
              foldKey={`flash-run:${run.id}:steps`}
              forceOpen={run.status === "running"}
              chips={[...new Set(run.steps.map((st) => st.status))].sort((a, b) => stepRank(a) - stepRank(b)).slice(0, 4).map((st) => (
                <StatChip key={st} n={run.steps.filter((x) => x.status === st).length}
                  tone={stepRank(st) === 0 ? "err" : stepRank(st) === 1 ? "warn" : st === "pass" ? "ok" : undefined}>
                  {st}
                </StatChip>
              ))}
            >
              <DataTable
                rows={run.steps}
                rowKey={(s) => s.idx}
                columns={STEP_COLS}
                defaultSort={{ key: "idx", dir: "asc" }}
                empty="No steps recorded."
              />
            </FoldSection>
            {run.results && Object.keys(run.results).length ? (
              <FoldSection title="Captured results" count={Object.keys(run.results).length} foldKey={`flash-run:${run.id}:results`}>
                <RunValues values={run.results} />
              </FoldSection>
            ) : null}
            {run.params_snapshot && Object.keys(run.params_snapshot).length ? (
              <FoldSection title="Applied parameters" count={Object.keys(run.params_snapshot).length} foldKey={`flash-run:${run.id}:params`}>
                <p className="muted dim">Secrets are masked in the snapshot itself.</p>
                <RunValues values={run.params_snapshot} />
              </FoldSection>
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
                <CheckField checked={follow} onChange={setFollow}>follow</CheckField>
                <span className="toolbar-total">{logs.length} lines</span>
              </div>
              <div ref={logBox} className="flash-log flash-log-tall mono">
                {logs.map((row) => (
                  <div key={row.seq} className={`fl-${row.dir}`} title={row.ts ?? ""}>
                    <span className="dim">{row.device_ts || (row.ts ? localTime(row.ts) : "")}</span>{" "}
                    {row.dir === "tx" ? "→ " : row.dir === "rx" ? "← " : `[${row.dir}] `}
                    {row.text}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
