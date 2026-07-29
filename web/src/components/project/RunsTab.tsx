/** Production batches of this project — a plain table. Everything about one batch
 *  (economics, materials, costs, files, serials, the sale) lives on the run's
 *  own page at /runs/:id; this tab only lists, creates and deletes. */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createRun,
  deleteRun,
  errorMessage,
  getRuns,
  isAbortError,
  type ProjectInfo,
  type RunInfo,
  type SnapshotInfo,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";

interface Props {
  project: ProjectInfo;
  snapshots: SnapshotInfo[];
  snapshot: SnapshotInfo | null;
  board: string;
  variant: string;
}

export default function RunsTab({ project, snapshots, snapshot, board, variant }: Props) {
  const [runs, setRuns] = useState<RunInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [label, setLabel] = useState("");
  const [qty, setQty] = useState(10);
  const [runDate, setRunDate] = useState("");
  const [creating, setCreating] = useState(false);
  const dialog = useDialog();
  const navigate = useNavigate();

  const load = (signal?: AbortSignal) => {
    getRuns(project.id, signal)
      .then((rows) => {
        setRuns(rows);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  };

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id]);

  const create = () => {
    setCreating(true);
    createRun(project.id, {
      label: label.trim(),
      snapshot_id: snapshot?.id ?? null,
      board: snapshot ? board : "",
      variant: snapshot ? variant : "",
      qty,
      run_date: runDate,
    })
      .then((r) => {
        setCreating(false);
        setShowNew(false);
        setLabel("");
        navigate(`/runs/${r.id}`);
      })
      .catch((err) => {
        setError(errorMessage(err));
        setCreating(false);
      });
  };

  return (
    <div>
      {error ? <ErrorBanner message={error} /> : null}
      <div className="toolbar">
        <span className="toolbar-total">{runs ? `${runs.length} batch(es)` : ""}</span>
        <button className="btn btn-primary btn-sm" onClick={() => setShowNew((v) => !v)}>
          {showNew ? "Cancel" : "New production batch"}
        </button>
      </div>

      {showNew ? (
        <div className="card pad edit-card">
          <div className="edit-grid">
            <label>
              Label
              <input className="text" value={label} placeholder="Run #1 — prototypes"
                onChange={(e) => setLabel(e.target.value)} />
            </label>
            <label>
              Quantity (devices)
              <input className="text" type="number" min="1" value={qty}
                onChange={(e) => setQty(Math.max(1, Number(e.target.value)))} />
            </label>
            <label>
              Date
              <input className="text" type="date" value={runDate}
                onChange={(e) => setRunDate(e.target.value)} />
            </label>
          </div>
          <p className="muted">
            {snapshot
              ? `Prices the BOM of ${snapshot.ref_name} / ${board}${variant ? ` (variant ${variant})` : ""} from price history at the run date (today if empty).`
              : "No snapshot selected — the batch will price only extra items and cost items."}
          </p>
          <button className="btn btn-primary" disabled={creating || !label.trim()} onClick={create}>
            {creating ? "Creating…" : "Create batch"}
          </button>
        </div>
      ) : null}

      {runs === null && !error ? <Spinner label="Loading runs" /> : null}
      {runs && runs.length > 0 ? (
        <div className="card table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Batch</th>
                <th className="num">Qty</th>
                <th>Status</th>
                <th>Date</th>
                <th>Snapshot</th>
                <th className="num">Files</th>
                <th className="num">Serials</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr
                  key={r.id}
                  className="ledger-row"
                  title={`Open ${r.label}`}
                  onClick={() => navigate(`/runs/${r.id}`)}
                >
                  <td>
                    <Link className="comp-link" to={`/runs/${r.id}`}>
                      {r.label}
                    </Link>
                  </td>
                  <td className="num">{r.qty}</td>
                  <td><StatusPill status={r.status} /></td>
                  <td className="muted">{r.run_date || "—"}</td>
                  <td className="mono">
                    {snapshots.find((s) => s.id === r.snapshot_id)?.ref_name ?? "—"}
                    {r.board ? ` / ${r.board}` : ""}
                  </td>
                  <td className="num">{r.attachment_count}</td>
                  <td className="num">{r.device_count}</td>
                  <td className="nowrap">
                    <Link className="btn btn-sm" to={`/runs/${r.id}`}>Open</Link>{" "}
                    <button className="btn btn-sm btn-danger"
                      onClick={async (e) => {
                        e.stopPropagation();
                        const confirmed = await dialog.confirm(
                          `Delete batch "${r.label}" and its attachments?`,
                          { title: "Delete production batch", confirmLabel: "Delete", tone: "danger" },
                        );
                        if (!confirmed) return;
                        deleteRun(r.id).then(() => load());
                      }}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {runs && runs.length === 0 && !showNew ? (
        <p className="muted">No production batches yet.</p>
      ) : null}
    </div>
  );
}
