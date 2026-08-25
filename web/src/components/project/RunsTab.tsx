/** Production batches of this project — a plain table. Everything about one batch
 *  (economics, materials, costs, files, serials, the sale) lives on the run's
 *  own page at /runs/:id; this tab only lists, creates and deletes. */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createRun,
  reviewWarningOf,
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
import DataTable, { type Column } from "../DataTable";

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

  const create = async (ack = false) => {
    setCreating(true);
    try {
      const r = await createRun(project.id, {
        label: label.trim(),
        snapshot_id: snapshot?.id ?? null,
        board: snapshot ? board : "",
        variant: snapshot ? variant : "",
        qty,
        run_date: runDate,
        ack_review: ack,
      });
      setCreating(false);
      setShowNew(false);
      setLabel("");
      navigate(`/runs/${r.id}`);
    } catch (err) {
      setCreating(false);
      // The design-review gate: a 409 naming what is unsigned / unreviewed /
      // deprecated (or a review never completed). Warn loudly, then let the
      // user proceed on an explicit confirmation — the ack is audited.
      const warning = reviewWarningOf(err);
      if (warning && !ack) {
        const parts: string[] = [];
        if (!warning.review_completed) parts.push("the design review of this snapshot was never completed");
        if (warning.changed_since_review.length)
          parts.push(`changed since the review: ${warning.changed_since_review.join(", ")}`);
        if (warning.unsigned.length) parts.push(`not signed off: ${warning.unsigned.join(", ")}`);
        if (warning.unreviewed.length) parts.push(`not verified: ${warning.unreviewed.join(", ")}`);
        if (warning.deprecated.length) parts.push(`deprecated parts: ${warning.deprecated.join(", ")}`);
        // Three-way, because "go fix it" is the answer this dialog exists
        // for: the review queue scoped to THIS snapshot's BOM is one click,
        // not a mental note to filter 400 rows later.
        const go = await dialog.confirm(
          `This snapshot is not review-clean:\n\n• ${parts.join("\n• ")}\n\nCreate the production batch anyway?`,
          { title: "Design review incomplete", confirmLabel: "Create anyway", tone: "danger",
            cancelLabel: "Not yet" },
        );
        if (go) return void create(true);
        if (
          snapshot &&
          (await dialog.confirm(
            "Open the review queue scoped to this snapshot's BOM?",
            { title: "Review first", confirmLabel: "Open review queue", tone: "ok" },
          ))
        )
          navigate(`/reviews?snapshot=${snapshot.id}`);
        return;
      }
      setError(errorMessage(err));
    }
  };

  const cols: Column<RunInfo>[] = [
    {
      key: "label",
      label: "Batch",
      width: 24,
      get: (r) => r.label,
      render: (r) => (
        <Link className="comp-link" to={`/runs/${r.id}`} onClick={(e) => e.stopPropagation()}>
          {r.label}
        </Link>
      ),
    },
    { key: "qty", label: "Qty", width: 7, numeric: true, get: (r) => r.qty },
    {
      key: "status",
      label: "Status",
      width: 11,
      get: (r) => r.status,
      render: (r) => <StatusPill status={r.status} />,
    },
    { key: "date", label: "Date", width: 11, className: "muted", get: (r) => r.run_date || "—" },
    {
      key: "snapshot",
      label: "Snapshot",
      width: 20,
      className: "mono",
      get: (r) =>
        (snapshots.find((s) => s.id === r.snapshot_id)?.ref_name ?? "—") +
        (r.board ? ` / ${r.board}` : ""),
    },
    { key: "files", label: "Files", width: 7, numeric: true, get: (r) => r.attachment_count },
    { key: "serials", label: "Serials", width: 7, numeric: true, get: (r) => r.device_count },
    {
      key: "actions",
      label: "",
      width: 13,
      interactive: false,
      className: "nowrap",
      get: () => "",
      render: (r) => (
        <>
          <Link className="btn btn-sm" to={`/runs/${r.id}`} onClick={(e) => e.stopPropagation()}>
            Open
          </Link>{" "}
          <button
            className="btn btn-sm btn-danger"
            onClick={async (e) => {
              e.stopPropagation();
              const confirmed = await dialog.confirm(
                `Delete batch "${r.label}" and its attachments?`,
                { title: "Delete production batch", confirmLabel: "Delete", tone: "danger" },
              );
              if (!confirmed) return;
              deleteRun(r.id).then(() => load());
            }}
          >
            Delete
          </button>
        </>
      ),
    },
  ];

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
          <button className="btn btn-primary" disabled={creating || !label.trim()} onClick={() => void create()}>
            {creating ? "Creating…" : "Create batch"}
          </button>
        </div>
      ) : null}

      {runs === null && !error ? <Spinner label="Loading runs" /> : null}
      {runs && runs.length > 0 ? (
        <div className="card table-wrap">
          <DataTable
            columns={cols}
            rows={runs}
            rowKey={(r) => r.id}
            persistKey="project-runs"
            rowClass={() => "ledger-row"}
            onRowClick={(r) => navigate(`/runs/${r.id}`)}
            empty="No production batches yet."
          />
        </div>
      ) : null}
      {runs && runs.length === 0 && !showNew ? (
        <p className="muted">No production batches yet.</p>
      ) : null}
    </div>
  );
}
