import { useState } from "react";
import {
  errorMessage,
  getWriteBatch,
  getWriteBatches,
  reverseWriteBatch,
  type WriteBatch,
  type WriteBatchRow,
} from "../../api";
import { Link } from "react-router-dom";
import { useAuth } from "../../auth";
import DataTable, { type Column } from "../DataTable";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";
import { localWhen } from "../../format";
import { useLoad } from "../useLoad";

const OP_TONE: Record<string, string> = { insert: "ok", delete: "err" };

const ROW_COLUMNS: Column<WriteBatchRow>[] = [
  { key: "table", label: "Table", width: 22, className: "mono", get: (r) => r.table },
  { key: "row", label: "Row", width: 10, className: "mono", get: (r) => r.row_id },
  { key: "op", label: "Op", width: 10, get: (r) => r.op,
    render: (r) => <span className={`pill ${OP_TONE[r.op] ?? "warn"}`}>{r.op}</span> },
  { key: "before", label: "Before", width: 58, className: "mono",
    get: (r) => (r.before ? JSON.stringify(r.before) : ""),
    render: (r) => (r.before ? JSON.stringify(r.before)
      : <span className="dim">— (insert: reversal deletes the row)</span>) },
];

/** Which rows a batch touched and how, read when its row opens. */
function BatchRows({ batch }: { batch: WriteBatch }) {
  // History → Everyone is admin-only, so only an admin is offered the link to it.
  const { isAdmin } = useAuth();
  const { data: rows, error } = useLoad(
    (signal) => getWriteBatch(batch.id, signal).then((d) => d.rows),
    [batch.id],
    { keep: true },
  );
  return (
    <>
      {isAdmin && batch.request_id ? (
        <p className="muted">
          <Link className="comp-link" to={`/history/all?request=${batch.request_id}`}>
            Everything this request wrote →
          </Link>{" "}
          the request, its events and every row it changed, in History → Everyone.
        </p>
      ) : null}
      <ErrorBanner message={error} />
      {rows === null && !error ? <Spinner label="loading batch rows" /> : null}
      {rows !== null ? <DataTable rows={rows} rowKey={(r) => r.id} columns={ROW_COLUMNS} /> : null}
    </>
  );
}

/**
 * Every write that moved money, and the button that puts it back.
 *
 * This is the screen whose absence produced eleven one-off Python scripts and a
 * run of raw SQL against a live ledger: the appliers were careful and gated, and
 * a mistake could only be corrected by writing another script.
 *
 * A refusal is shown in full rather than summarised. "Cannot reverse" is useless;
 * "row run_cost_lines#1047 was edited after this batch" is actionable, and the
 * distinction matters because silently discarding a later hand correction in
 * order to satisfy an undo is exactly how a substitution link was destroyed
 * twice during the backfill.
 */
export default function WriteLog({ onReversed }: { onReversed?: () => void } = {}) {
  const dialog = useDialog();
  const { data, loading, error, reload: load } = useLoad(
    (signal) => getWriteBatches({ limit: 40 }, signal).then((r) => r.batches),
    [],
  );
  const batches = data ?? [];
  const [busy, setBusy] = useState<number | null>(null);
  const [plan, setPlan] = useState<Record<number, string>>({});

  async function preview(b: WriteBatch) {
    setBusy(b.id);
    try {
      const r = await reverseWriteBatch(b.id, true);
      setPlan((p) => ({
        ...p,
        [b.id]:
          `would delete ${r.would.delete}, restore ${r.would.restore}, ` +
          `re-insert ${r.would.reinsert} row(s)`,
      }));
    } catch (err) {
      setPlan((p) => ({ ...p, [b.id]: errorMessage(err) }));
    } finally {
      setBusy(null);
    }
  }

  async function undo(b: WriteBatch) {
    const label = `${b.kind} ${b.source_ref}`.trim();
    const ok = await dialog.confirm(
      `Reverse batch ${b.id} (${label})? This puts every row it touched back as it was, ` +
        `and re-checks the register against the state before the batch ran. It refuses if ` +
        `anything was edited since.`,
      { title: "Undo this write", confirmLabel: "Undo", tone: "danger" },
    );
    if (!ok) return;
    setBusy(b.id);
    try {
      await reverseWriteBatch(b.id, false);
      setPlan((p) => ({ ...p, [b.id]: "" }));
      load();
      onReversed?.();
    } catch (err) {
      setPlan((p) => ({ ...p, [b.id]: errorMessage(err) }));
    } finally {
      setBusy(null);
    }
  }

  // Only the first load: a reload after an undo keeps the table and its open row.
  if (loading && !batches.length) return <Spinner label="loading the write log" />;

  // The undo column is widest because it carries a refusal naming the rows that
  // block the reversal. That text is the only actionable part, so it wraps.
  const columns: Column<WriteBatch>[] = [
    { key: "id", label: "#", width: 8, className: "mono", get: (b) => b.id },
    { key: "kind", label: "What", width: 15, get: (b) => b.kind,
      render: (b) => (
        <>
          {b.kind}
          {b.kind === "reverse" ? <span className="pill neutral">undo</span> : null}
        </>
      ) },
    { key: "source", label: "Source", width: 13, className: "mono", get: (b) => b.source_ref || "—" },
    { key: "when", label: "When", width: 17, className: "muted dim", get: (b) => b.created_at ?? "",
      render: (b) => (b.created_at ? localWhen(b.created_at) : "—") },
    { key: "by", label: "By", width: 13, get: (b) => b.actor || "—" },
    { key: "rows", label: "Rows", width: 12, get: (b) => b.row_count,
      render: (b) => (
        <>
          {b.row_count}{" "}
          <span className="muted dim">({Object.entries(b.by_op).map(([k, v]) => `${v} ${k}`).join(", ")})</span>
        </>
      ) },
    { key: "undo", label: "Undo", width: 22, interactive: false, get: () => "",
      render: (b) => (
        <>
          {b.reversed_at ? (
            <span className="pill neutral">reversed by {b.reversed_by_batch_id}</span>
          ) : (
            <div className="btn-row">
              <button className="btn btn-sm" disabled={busy === b.id}
                onClick={(e) => { e.stopPropagation(); void preview(b); }}>
                Check
              </button>
              <button className="btn btn-sm btn-danger" disabled={busy === b.id}
                onClick={(e) => { e.stopPropagation(); void undo(b); }}>
                Undo
              </button>
            </div>
          )}
          {plan[b.id] ? <div className="muted dim cell-wrap">{plan[b.id]}</div> : null}
        </>
      ) },
  ];

  return (
    <div className="card pad">
      <h2 className="card-title">Recent writes</h2>
      <p className="muted dim">
        Everything that moved money, newest first. Reversing re-asserts the register against the
        state before the batch ran — not against zero — so a standing gap cannot make an undo
        impossible.
      </p>
      <ErrorBanner message={error} />
      <div className="table-wrap">
        <DataTable
          rows={batches}
          rowKey={(b) => b.id}
          columns={columns}
          expand={(b) => <BatchRows batch={b} />}
          empty="Nothing yet. Imports and decisions applied through the UI appear here, each undoable."
        />
      </div>
    </div>
  );
}
