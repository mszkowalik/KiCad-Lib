/** Production → Batches: every production batch, across every project.
 *
 *  The project's own Batches tab answers "what has this product built"; this
 *  answers "what is in production anywhere", which had no home. The only
 *  cross-project list was the invoice register's table on Cost overview, so a
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
import { NarrowChip } from "../components/FoldSection";
import { MiniBoard, nextUp } from "../components/process/ProcessBoard";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { useAuth } from "../auth";
import { localDate, plural } from "../format";

const isPlanned = (r: RunInfo) => (r.status || "").trim().toLowerCase() === "planned";

export default function Runs() {
  const [runs, setRuns] = useState<RunInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [narrow, setNarrow] = useState<"" | "work" | "planned" | "open" | "closed">("");
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
      planned: rows.filter(isPlanned).length,
    };
  }, [runs]);

  const { companyName } = useAuth();
  const cols: Column<RunInfo>[] = [
    {
      key: "label",
      label: "Batch",
      width: 20,
      get: (r) => r.label,
      render: (r) => (
        <Link className="comp-link" to={`/production/batches/${r.id}`} onClick={(e) => e.stopPropagation()}>
          {r.label}
        </Link>
      ),
    },
    { key: "project", label: "Project", width: 11, className: "muted", get: (r) => r.project || "—" },
    { key: "company", label: "Company", width: 6, get: (r) => companyName(r.company_id) },
    { key: "date", label: "Date", width: 8, className: "mono", get: (r) => r.run_date || "—" },
    {
      key: "process",
      label: "Board",
      width: 15,
      interactive: false,
      get: () => "",
      render: (r) => (r.process_board ? <MiniBoard steps={r.process_board} /> : null),
    },
    {
      key: "next",
      label: "Can go now",
      width: 11,
      get: (r) => {
        const up = r.process_board ? nextUp(r.process_board) : null;
        return up ? `${up.can_go.toLocaleString()} at ${up.label}` : "";
      },
    },
    {
      key: "status",
      label: "Status",
      width: 12,
      get: (r) => r.status,
      render: (r) => <StatusPill status={r.status} />,
    },
    { key: "qty", label: "Qty", width: 6, numeric: true, get: (r) => r.qty },
    // What the batch actually MADE — `DeviceUnit.production_run_id`, counted by
    // the server. Never `run_devices`, the hand-typed registry that has never
    // held a row and read 0 for every batch until 2026-09-19.
    {
      key: "devices",
      label: "Devices",
      width: 6,
      numeric: true,
      get: (r) => r.device_count ?? 0,
      title: () => "devices recorded as produced on this batch",
    },
    {
      key: "books",
      label: "Books",
      width: 5,
      get: (r) => (r.closed_at ? "closed" : "open"),
      title: (r) =>
        r.closed_at
          ? `Closed ${localDate(r.closed_at)}${r.closed_by ? ` by ${r.closed_by}` : ""} — every `
            + "document charging this batch, written before then, is read-only (decision 0044)"
          : "Its invoices can still be edited, and its per-device cost still moves",
      render: (r) =>
        r.closed_at ? <span title="closed">🔒</span> : <span className="muted">open</span>,
    },
  ];

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Batches</h1>
          {runs ? (
            <span className="toolbar-total">
              {plural(totals.batches, "batch", "batches")}
              {totals.planned ? ` · ${totals.planned} planned` : ""}
              {` · ${totals.devices.toLocaleString()} devices recorded`}
            </span>
          ) : null}
        </div>

        {error ? <ErrorBanner message={error} /> : null}

        <div className="card pad">
          <p className="card-subtitle">Every batch, across every project</p>
          <p className="muted dim">
            Qty is what was ordered or assembled; Devices is what the batch is recorded to
            have made, which is the denominator of its per-device cost. What each batch COST
            is on <Link to="/finance">Finance → Cost overview</Link>, and everything about one batch —
            economics, materials, files, serials — is on its own page. A batch is created
            from its project, where the snapshot and board are already chosen.
          </p>
          {!runs ? (
            <Spinner label="Loading batches…" />
          ) : (
            <div className="table-wrap">
              <div className="stat-row">
                <NarrowChip n={runs.filter((r) => r.process_board).length} tone="acc" value="work" current={narrow} onNarrow={setNarrow}>in work</NarrowChip>
                <NarrowChip n={totals.planned} value="planned" current={narrow} onNarrow={setNarrow}>planned</NarrowChip>
                <NarrowChip n={runs.filter((r) => !r.closed_at).length} value="open" current={narrow} onNarrow={setNarrow}>books open</NarrowChip>
                <NarrowChip n={runs.filter((r) => r.closed_at).length} tone="ok" value="closed" current={narrow} onNarrow={setNarrow}>books closed</NarrowChip>
              </div>
              <DataTable
                columns={cols}
                rows={runs.filter((r) =>
                  narrow === "work" ? r.process_board
                    : narrow === "planned" ? isPlanned(r)
                      : narrow === "open" ? !r.closed_at
                        : narrow === "closed" ? r.closed_at
                          : true)}
                rowKey={(r) => r.id}
                // The server already returns newest first, but a table has to
                // SAY so: without a default the header shows no arrow, and a
                // sort the reader set once is remembered under `persistKey` and
                // silently outlives the visit that set it.
                defaultSort={{ key: "date", dir: "desc" }}
                persistKey="all-runs"
                onRowClick={(r) => navigate(`/production/batches/${r.id}`)}
                // A batch in work comes first, whatever the sort.
                group={(r) => (r.process_board ? 0 : 1)}
                empty="No production batch exists yet."
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
