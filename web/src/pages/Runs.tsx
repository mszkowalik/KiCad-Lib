/** Production → Batches: every production batch, across every project.
 *
 *  The project's own Batches tab answers "what has this product built"; this
 *  answers "what is in production anywhere", which had no home. The only
 *  cross-project list was the invoice register's table on the Overview, so a
 *  batch nobody had billed yet was invisible, and that table is about MONEY —
 *  what each batch cost. This one is about the batches themselves: what state
 *  they are in, how many devices they made, whether their books are closed.
 *
 *  It does not create batches: a batch belongs to a project, so the New button
 *  stays on the project's tab where the snapshot and board are already chosen.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  errorMessage,
  getAllRuns,
  isAbortError,
  type RunInfo,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";

export default function Runs() {
  const [runs, setRuns] = useState<RunInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const ctrl = new AbortController();
    getAllRuns(ctrl.signal)
      .then((rows) => {
        setRuns(rows);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, []);

  const totals = useMemo(() => {
    const rows = runs ?? [];
    return {
      batches: rows.length,
      devices: rows.reduce((n, r) => n + (r.device_count ?? 0), 0),
      planned: rows.filter((r) => (r.status || "").trim().toLowerCase() === "planned").length,
    };
  }, [runs]);

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
    { key: "project", label: "Project", width: 13, className: "muted", get: (r) => r.project || "—" },
    { key: "date", label: "Date", width: 10, className: "mono", get: (r) => r.run_date || "—" },
    {
      key: "status",
      label: "Status",
      width: 10,
      get: (r) => r.status,
      render: (r) => <StatusPill status={r.status} />,
    },
    { key: "qty", label: "Qty", width: 7, numeric: true, get: (r) => r.qty },
    // What the batch actually MADE — `DeviceUnit.production_run_id`, counted by
    // the server. Never `run_devices`, the hand-typed registry that has never
    // held a row and read 0 for every batch until 2026-09-19.
    {
      key: "devices",
      label: "Devices",
      width: 8,
      numeric: true,
      get: (r) => r.device_count ?? 0,
      title: () => "devices recorded as produced on this batch",
    },
    {
      key: "board",
      label: "Board",
      width: 17,
      className: "mono",
      // Clips on `ProPrj_CE_AQUA_V2_2026-07-27`, and is left to: the board name
      // is secondary here (Project already names the product) and DataTable
      // puts the full value in the cell's title. Widening it to 21% to fit one
      // historical name would take the width from the batch label, which is the
      // identifier and the link.
      get: (r) => r.board + (r.variant ? ` / ${r.variant}` : ""),
    },
    {
      key: "books",
      label: "Books",
      width: 11,
      get: (r) => (r.closed_at ? "closed" : "open"),
      title: (r) =>
        r.closed_at
          ? `Closed ${r.closed_at.slice(0, 10)}${r.closed_by ? ` by ${r.closed_by}` : ""} — every `
            + "document charging this batch, written before then, is read-only (decision 0044)"
          : "Its invoices can still be edited, and its per-device cost still moves",
      render: (r) =>
        r.closed_at ? <span className="pill neutral">🔒 closed</span> : <span className="muted">open</span>,
    },
  ];

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1 className="page-title">Batches</h1>
          {runs ? (
            <span className="toolbar-total">
              {totals.batches} batch{totals.batches === 1 ? "" : "es"}
              {totals.planned ? ` · ${totals.planned} planned` : ""}
              {` · ${totals.devices.toLocaleString()} devices recorded`}
            </span>
          ) : null}
        </div>

        {error ? <ErrorBanner message={error} /> : null}

        <div className="card pad">
          <p className="card-subtitle">
            Every production batch in the platform, newest first. Qty is what was ordered or
            assembled; Devices is what the batch is recorded to have made, which is the
            denominator of its per-device cost. What each batch COST is on{" "}
            <Link to="/production">Overview</Link>, and everything about one batch — economics,
            materials, files, serials — is on its own page. A batch is created from its project,
            where the snapshot and board are already chosen.
          </p>
          {!runs ? (
            <Spinner label="Loading batches…" />
          ) : (
            <div className="table-wrap">
              <DataTable
                columns={cols}
                rows={runs}
                rowKey={(r) => r.id}
                persistKey="all-runs"
                onRowClick={(r) => navigate(`/runs/${r.id}`)}
                empty="No production batch exists yet."
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
