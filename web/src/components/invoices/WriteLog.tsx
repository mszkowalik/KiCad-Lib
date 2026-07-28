import { useCallback, useEffect, useState } from "react";
import {
  errorMessage,
  getWriteBatches,
  isAbortError,
  reverseWriteBatch,
  type WriteBatch,
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
                  <tr key={b.id}>
                    <td className="mono">{b.id}</td>
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
                            onClick={() => preview(b)}
                          >
                            Check
                          </button>
                          <button
                            className="btn btn-sm btn-danger"
                            disabled={busy === b.id}
                            onClick={() => undo(b)}
                          >
                            Undo
                          </button>
                        </div>
                      )}
                      {plan[b.id] && <div className="muted dim">{plan[b.id]}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
