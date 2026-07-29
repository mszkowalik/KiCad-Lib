import { Fragment, useCallback, useEffect, useState } from "react";
import {
  errorMessage,
  getWriteBatch,
  getWriteBatches,
  isAbortError,
  reverseWriteBatch,
  type WriteBatch,
  type WriteBatchRow,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";

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
  const [batches, setBatches] = useState<WriteBatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [plan, setPlan] = useState<Record<number, string>>({});
  // Row-level detail, loaded on demand: which rows a batch touched and how.
  const [open, setOpen] = useState<number | null>(null);
  const [detail, setDetail] = useState<Record<number, WriteBatchRow[] | string>>({});

  const toggleDetail = (id: number) => {
    if (open === id) {
      setOpen(null);
      return;
    }
    setOpen(id);
    if (!detail[id]) {
      getWriteBatch(id)
        .then((d) => setDetail((p) => ({ ...p, [id]: d.rows })))
        .catch((err) => setDetail((p) => ({ ...p, [id]: errorMessage(err) })));
    }
  };

  const load = useCallback((signal?: AbortSignal) => {
    setLoading(true);
    getWriteBatches({ limit: 40 }, signal)
      .then((r) => {
        setBatches(r.batches);
        setError("");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

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

  if (loading) return <Spinner label="loading the write log" />;

  return (
    <div className="card">
      <h2 className="card-title">Recent writes</h2>
      <p className="card-subtitle">
        Everything that moved money, newest first. Reversing re-asserts the register against the
        state before the batch ran — not against zero — so a standing gap cannot make an undo
        impossible.
      </p>
      <ErrorBanner message={error} />
      {batches.length === 0 && (
        <p className="muted">
          Nothing yet. Imports and decisions applied through the UI appear here, each undoable.
        </p>
      )}
      <div className="table-wrap">
        {batches.length > 0 && (
          <table className="data data-fixed write-log-table">
            <thead>
              <tr>
                <th>#</th>
                <th>what</th>
                <th>source</th>
                <th>when</th>
                <th>rows</th>
                <th>undo</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => {
                const reversed = !!b.reversed_at;
                const ops = Object.entries(b.by_op)
                  .map(([k, v]) => `${v} ${k}`)
                  .join(", ");
                return (
                  <Fragment key={b.id}>
                  <tr className="ledger-row" onClick={() => toggleDetail(b.id)}
                      title="Click for the rows this batch touched">
                    <td className="mono">
                      <span className="ledger-caret">{open === b.id ? "▾" : "▸"}</span>
                      {b.id}
                    </td>
                    <td>
                      {b.kind}
                      {b.kind === "reverse" && <span className="pill neutral">undo</span>}
                    </td>
                    <td className="mono cell-desc">{b.source_ref || "—"}</td>
                    <td className="muted dim">
                      {b.created_at ? new Date(b.created_at).toLocaleString() : "—"}
                    </td>
                    <td>
                      {b.row_count} <span className="muted dim">({ops})</span>
                    </td>
                    <td>
                      {reversed ? (
                        <span className="pill neutral">
                          reversed by {b.reversed_by_batch_id}
                        </span>
                      ) : (
                        <div className="btn-row">
                          <button
                            className="btn btn-sm"
                            disabled={busy === b.id}
                            onClick={(e) => {
                              e.stopPropagation();
                              void preview(b);
                            }}
                          >
                            Check
                          </button>
                          <button
                            className="btn btn-sm btn-danger"
                            disabled={busy === b.id}
                            onClick={(e) => {
                              e.stopPropagation();
                              void undo(b);
                            }}
                          >
                            Undo
                          </button>
                        </div>
                      )}
                      {plan[b.id] && <div className="muted dim">{plan[b.id]}</div>}
                    </td>
                  </tr>
                  {open === b.id && (
                    <tr>
                      <td colSpan={6} className="ledger-cell">
                        {detail[b.id] == null ? (
                          <Spinner label="loading batch rows" />
                        ) : typeof detail[b.id] === "string" ? (
                          <ErrorBanner message={detail[b.id] as string} />
                        ) : (
                          <div className="table-wrap">
                            <table className="data">
                              <thead>
                                <tr>
                                  <th>table</th>
                                  <th>row</th>
                                  <th>op</th>
                                  <th>before</th>
                                </tr>
                              </thead>
                              <tbody>
                                {(detail[b.id] as WriteBatchRow[]).map((r) => (
                                  <tr key={r.id}>
                                    <td className="mono">{r.table}</td>
                                    <td className="mono">{r.row_id}</td>
                                    <td>
                                      <span
                                        className={`pill ${
                                          r.op === "insert"
                                            ? "ok"
                                            : r.op === "delete"
                                              ? "err"
                                              : "warn"
                                        }`}
                                      >
                                        {r.op}
                                      </span>
                                    </td>
                                    <td
                                      className="mono cell-desc"
                                      title={r.before ? JSON.stringify(r.before) : ""}
                                    >
                                      {r.before ? (
                                        JSON.stringify(r.before)
                                      ) : (
                                        <span className="dim">
                                          — (insert: reversal deletes the row)
                                        </span>
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
