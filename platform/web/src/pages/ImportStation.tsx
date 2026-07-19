import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  errorMessage,
  getImportStatus,
  startImport,
  startSync,
  type ImportReport,
  type ImportStatus,
} from "../api";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";

const CONFIRM_WORD = "IMPORT";
const POLL_MS = 1500;

const COUNT_FIELDS: Array<{ key: keyof ImportReport; label: string }> = [
  { key: "libraries", label: "Libraries" },
  { key: "categories", label: "Categories" },
  { key: "components", label: "Components" },
  { key: "properties", label: "Properties" },
  { key: "symbols", label: "Symbols" },
  { key: "footprints", label: "Footprints" },
  { key: "models3d", label: "3D models" },
  { key: "rules", label: "Rules" },
  { key: "skills", label: "Skills" },
  { key: "duration_s", label: "Duration (s)" },
];

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function CountsGrid({ report }: { report: ImportReport }) {
  // Failed runs carry their numbers under `partial`.
  const counts = report.partial ?? report;
  return (
    <div className="counts">
      {COUNT_FIELDS.map(({ key, label }) => {
        const v = counts[key];
        return (
          <div className="count-tile" key={key}>
            <div className="v">{typeof v === "number" ? v : "—"}</div>
            <div className="k">{label}</div>
          </div>
        );
      })}
    </div>
  );
}

function WarningsList({ title, warnings }: { title: string; warnings: string[] }) {
  if (warnings.length === 0) {
    return <p className="muted no-warnings">No {title.toLowerCase()}.</p>;
  }
  return (
    <details className="warnings">
      <summary>
        {title} <span className="mono">({warnings.length})</span>
      </summary>
      <ul>
        {warnings.map((w, i) => (
          <li key={i} className="mono">
            {w}
          </li>
        ))}
      </ul>
    </details>
  );
}

function ReportView({ report }: { report: ImportReport }) {
  const warnings = report.warnings ?? report.partial?.warnings ?? [];
  return (
    <>
      {report.error ? (
        <details className="warnings failed-trace" open>
          <summary>Import failed — traceback</summary>
          <pre>{report.error}</pre>
        </details>
      ) : null}
      <CountsGrid report={report} />
      <WarningsList title="Warnings" warnings={warnings} />
      {report.mirror ? (
        <div className="mirror">
          <h4 className="card-subtitle">File mirror</h4>
          <div className="counts counts-sm">
            <div className="count-tile">
              <div className="v">{report.mirror.symbol_libs}</div>
              <div className="k">Symbol libs</div>
            </div>
            <div className="count-tile">
              <div className="v">{report.mirror.components_in_libs}</div>
              <div className="k">Components in libs</div>
            </div>
            <div className="count-tile">
              <div className="v">{report.mirror.footprints}</div>
              <div className="k">Footprints</div>
            </div>
            <div className="count-tile">
              <div className="v">{report.mirror.models3d}</div>
              <div className="k">3D models</div>
            </div>
          </div>
          <WarningsList title="Mirror warnings" warnings={report.mirror.warnings} />
        </div>
      ) : null}
    </>
  );
}

function SyncReportView({ live, report }: { live: boolean; report: ImportReport }) {
  const newP = report.new_proposals ?? [];
  const edits = report.edit_proposals ?? [];
  const pending = report.already_pending ?? [];
  const skipped = report.skipped ?? [];
  const onlyDb = report.only_in_db ?? [];
  const created = report.proposals_created ?? 0;
  const tiles: Array<[string, number | undefined]> = [
    ["New proposals", newP.length],
    ["Edits proposed", edits.length],
    ["Unchanged", report.unchanged],
    ["Already pending", pending.length],
    ["Skipped", skipped.length],
    ["Only in DB", onlyDb.length],
    ["Duration (s)", report.duration_s],
  ];
  return (
    <>
      {report.error ? (
        <details className="warnings failed-trace" open>
          <summary>Sync failed — traceback</summary>
          <pre>{report.error}</pre>
        </details>
      ) : null}
      <div className="counts">
        {tiles.map(([label, v]) => (
          <div className="count-tile" key={label}>
            <div className="v">{typeof v === "number" ? v : "—"}</div>
            <div className="k">{label}</div>
          </div>
        ))}
      </div>
      {created > 0 && live ? (
        <p className="banner-ok">
          {created} draft {created === 1 ? "proposal" : "proposals"} created.{" "}
          <Link to="/proposals">Review in Proposals →</Link>
        </p>
      ) : created === 0 && !report.error ? (
        <p className="muted no-warnings">No differences — nothing to propose.</p>
      ) : null}
      <WarningsList title="New components" warnings={newP} />
      <WarningsList title="Changed components" warnings={edits} />
      <WarningsList title="Already pending (proposal exists)" warnings={pending} />
      <WarningsList title="Skipped" warnings={skipped.map((s) => `${s.name} — ${s.reason}`)} />
      <WarningsList title="In DB but not in YAML" warnings={onlyDb} />
      <WarningsList title="Warnings" warnings={report.warnings ?? []} />
    </>
  );
}

export default function ImportStation() {
  const [status, setStatus] = useState<ImportStatus | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  const [starting, setStarting] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const s = await getImportStatus();
      setStatus(s);
      setFetchError(null);
    } catch (err) {
      setFetchError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const running = status?.running ?? false;

  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => {
      void refresh();
    }, POLL_MS);
    return () => window.clearInterval(t);
  }, [running, refresh]);

  const start = async () => {
    setStarting(true);
    setActionError(null);
    try {
      await startImport();
      setConfirm("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Someone else started one — just follow it.
        setConfirm("");
      } else {
        setActionError(errorMessage(err));
      }
    } finally {
      setStarting(false);
      void refresh();
    }
  };

  const startSyncing = async () => {
    setSyncing(true);
    setActionError(null);
    try {
      await startSync();
    } catch (err) {
      // 409 = a job is already running; just follow it via polling.
      if (!(err instanceof ApiError && err.status === 409)) {
        setActionError(errorMessage(err));
      }
    } finally {
      setSyncing(false);
      void refresh();
    }
  };

  const canStart = confirm === CONFIRM_WORD && !running && !starting && !syncing;
  const lastRun = status?.last_run ?? null;
  // Prefer the in-process report from the run just finished; otherwise the persisted one.
  const report = status?.report ?? lastRun?.report ?? null;

  return (
    <div className="main-solo">
      <div className="page">
        <h1>Import station</h1>

        {fetchError ? <ErrorBanner message={`Status failed to load: ${fetchError}`} /> : null}
        {actionError ? <ErrorBanner message={`Couldn't start: ${actionError}`} /> : null}

        <section className="card pad">
          <h3 className="card-title">Sync from YAML</h3>
          <p>
            Compares <span className="mono">Sources/*.yaml</span> against the database and creates{" "}
            <strong>draft proposals</strong> for new and changed components. Non-destructive: nothing
            is wiped, deleted, or published — you review and approve the proposals in{" "}
            <Link to="/proposals">Proposals</Link>.
          </p>
          <div className="btn-row">
            <button
              type="button"
              className="btn btn-primary"
              disabled={running || starting || syncing}
              onClick={() => void startSyncing()}
            >
              Sync from YAML
            </button>
          </div>
        </section>

        <section className="card pad danger-card">
          <h3 className="card-title">Wipe &amp; re-import</h3>
          <p>
            Importing <strong>wipes the entire database</strong> — components, versions,
            categories, symbols, footprints and audit history — and reloads everything from the
            repository working tree. This cannot be undone.
          </p>
          <p className="muted">
            Type <span className="mono confirm-word">{CONFIRM_WORD}</span> to enable the button.
          </p>
          <div className="confirm-row">
            <input
              type="text"
              className="text mono"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder={CONFIRM_WORD}
              disabled={running}
              aria-label={`Type ${CONFIRM_WORD} to confirm`}
              autoComplete="off"
              spellCheck={false}
            />
            <button type="button" className="btn btn-danger" disabled={!canStart} onClick={() => void start()}>
              Wipe &amp; re-import
            </button>
          </div>
        </section>

        {running ? (
          <section className="card pad live-card">
            <h3 className="card-title">Running</h3>
            <div className="live-stage">
              <Spinner />
              <span className="mono">{status?.stage || "…"}</span>
            </div>
            {status?.started_at ? (
              <p className="muted">Started {fmtDate(status.started_at)}</p>
            ) : null}
          </section>
        ) : null}

        {!running && status?.error ? (
          <section className="card pad">
            <h3 className="card-title">Last attempt failed</h3>
            <details className="warnings failed-trace" open>
              <summary>Traceback</summary>
              <pre>{status.error}</pre>
            </details>
          </section>
        ) : null}

        {!running && report ? (
          <section className="card pad">
            <h3 className="card-title">
              {report.mode === "sync"
                ? status?.report
                  ? "Sync report"
                  : "Last sync report"
                : status?.report
                  ? "Import report"
                  : "Last run report"}
            </h3>
            {report.mode === "sync" ? (
              <SyncReportView live={status?.report != null} report={report} />
            ) : (
              <ReportView report={report} />
            )}
          </section>
        ) : null}

        {lastRun ? (
          <section className="card pad">
            <h3 className="card-title">Last run</h3>
            <dl className="kv">
              <dt>Run</dt>
              <dd className="mono">#{lastRun.id}</dd>
              <dt>Status</dt>
              <dd>
                <StatusPill status={lastRun.status} />
              </dd>
              <dt>Started</dt>
              <dd className="mono">{fmtDate(lastRun.started_at)}</dd>
              <dt>Finished</dt>
              <dd className="mono">{fmtDate(lastRun.finished_at)}</dd>
              <dt>Duration</dt>
              <dd className="mono">{lastRun.duration_s != null ? `${lastRun.duration_s} s` : "—"}</dd>
            </dl>
          </section>
        ) : status !== null && !running ? (
          <p className="muted">No import has been run yet.</p>
        ) : null}

        {status === null && !fetchError ? (
          <div className="block-loading">
            <Spinner label="Loading status" />
          </div>
        ) : null}
      </div>
    </div>
  );
}
