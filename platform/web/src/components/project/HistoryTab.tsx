/** Git history: commits + tags from the local mirror, snapshot status per
 *  commit, ingest-on-demand, and snapshot selection for the other tabs. */
import { useEffect, useState } from "react";
import {
  errorMessage,
  getProjectHistory,
  ingestSnapshot,
  isAbortError,
  type ProjectHistory,
  type ProjectInfo,
  type SnapshotInfo,
} from "../../api";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { useStickyState } from "../../useStickyState";

interface Props {
  project: ProjectInfo;
  snapshots: SnapshotInfo[];
  selectedSnapshotId: number | null;
  onSelectSnapshot: (id: number) => void;
  onIngested: () => void;
}

export default function HistoryTab({
  project,
  snapshots,
  selectedSnapshotId,
  onSelectSnapshot,
  onIngested,
}: Props) {
  const [history, setHistory] = useState<ProjectHistory | null>(null);
  const [ref, setRef] = useStickyState(`project:${project.id}:history:branch`, "");
  const [error, setError] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setError(null);
    getProjectHistory(project.id, ref || undefined, ctrl.signal)
      .then(setHistory)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, ref, snapshots.length]);

  const snapBySha = new Map(snapshots.map((s) => [s.sha, s]));

  const ingest = (refOrSha: string) => {
    setIngesting(refOrSha);
    ingestSnapshot(project.id, refOrSha)
      .then(() => {
        setIngesting(null);
        onIngested();
      })
      .catch((err) => {
        setError(errorMessage(err));
        setIngesting(null);
      });
  };

  if (!project.has_mirror) {
    return (
      <p className="muted">
        Repository not fetched yet — use the Fetch button in the header first.
      </p>
    );
  }

  return (
    <div>
      {error ? <ErrorBanner message={error} /> : null}
      {history === null && !error ? <Spinner label="Reading git history" /> : null}
      {history ? (
        <>
          <div className="toolbar">
            <label className="proj-inline-field">
              Branch
              <select className="text" value={ref} onChange={(e) => setRef(e.target.value)}>
                <option value="">{history.branch} (default)</option>
                {history.branches
                  .filter((b) => b.name !== history.branch)
                  .map((b) => (
                    <option key={b.name} value={b.name}>
                      {b.name}
                    </option>
                  ))}
              </select>
            </label>
            {history.tags.length > 0 ? (
              <span className="muted">
                tags: {history.tags.map((t) => t.name).join(", ")}
              </span>
            ) : (
              <span className="muted">no tags yet</span>
            )}
          </div>
          <div className="card table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Commit</th>
                  <th>Message</th>
                  <th>Author</th>
                  <th>Date</th>
                  <th>Refs</th>
                  <th>Snapshot</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {history.commits.map((c) => {
                  const snap = snapBySha.get(c.sha);
                  const selected = snap && snap.id === selectedSnapshotId;
                  return (
                    <tr key={c.sha} className={selected ? "row-selected" : ""}>
                      <td className="mono">{c.sha.slice(0, 10)}</td>
                      <td className="cell-desc" title={c.message}>
                        {c.message}
                      </td>
                      <td className="muted">{c.author}</td>
                      <td className="muted nowrap">{new Date(c.date).toLocaleDateString()}</td>
                      <td className="mono cell-cat">{c.refs.join(", ")}</td>
                      <td>
                        {snap ? <StatusPill status={snap.status} /> : <span className="muted">—</span>}
                      </td>
                      <td className="nowrap">
                        {snap && snap.status === "ready" ? (
                          <button
                            className="btn btn-sm"
                            disabled={!!selected}
                            onClick={() => onSelectSnapshot(snap.id)}
                          >
                            {selected ? "Viewing" : "View"}
                          </button>
                        ) : snap && (snap.status === "ingesting" || snap.status === "pending") ? (
                          <Spinner />
                        ) : (
                          <button
                            className="btn btn-sm"
                            disabled={ingesting !== null}
                            onClick={() => ingest(c.sha)}
                          >
                            {ingesting === c.sha ? "Starting…" : snap ? "Retry" : "Ingest"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
