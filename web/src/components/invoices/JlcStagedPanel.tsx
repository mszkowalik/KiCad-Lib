import { useCallback, useEffect, useState } from "react";
import {
  applyJlcDocument,
  applyJlcParts,
  errorMessage,
  getJlcPartsOrders,
  getJlcStaged,
  isAbortError,
  type JlcPartsOrder,
  type JlcStagedRow,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";

/**
 * Staged JLC batches, and the button that turns one into a cost document.
 *
 * Sync deliberately only STAGES: a scrape of an undocumented, unversioned API must
 * not move money unattended, so a shape change surfaces as a payload someone looks
 * at rather than as a wrong number in the register. This is the second half — the
 * part that was reachable only by running `import_all.py` inside the container.
 *
 * Preview runs the REAL write path with `dry_run=true` and rolls back, so the
 * figures shown are the figures the import produces. A re-implementation of the
 * mapping could disagree with the mapping; the same code cannot.
 */
export default function JlcStagedPanel({ onImported }: { onImported?: () => void } = {}) {
  const dialog = useDialog();
  const [rows, setRows] = useState<JlcStagedRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [plan, setPlan] = useState<Record<string, string>>({});
  const [onlyPending, setOnlyPending] = useState(true);
  // Parts orders are fetched LIVE — sync stages assembly batches only.
  const [parts, setParts] = useState<JlcPartsOrder[] | null>(null);
  const [partsErr, setPartsErr] = useState("");

  const load = useCallback((signal?: AbortSignal) => {
    setLoading(true);
    getJlcStaged(signal)
      .then((r) => {
        setRows(r);
        setError("");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      })
      .finally(() => setLoading(false));
    // Separate failure path: a dead session breaks this and not the staged list,
    // which is local. Collapsing them would blame staging for a network problem.
    getJlcPartsOrders(signal)
      .then((r) => {
        setParts(r.orders);
        setPartsErr("");
      })
      .catch((err) => {
        if (!isAbortError(err)) setPartsErr(errorMessage(err));
      });
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  async function preview(r: JlcStagedRow) {
    setBusy(r.external_id);
    try {
      const res = await applyJlcDocument(r.external_id, true);
      const p = (res.plan ?? {}) as Record<string, unknown>;
      const result = (res.result ?? {}) as Record<string, unknown>;
      setPlan((prev) => ({
        ...prev,
        [r.external_id]:
          `${(res.lines ?? []).length} lines, $${p.total_amount ?? "?"}` +
          (p.reconciles === false ? " — DOES NOT RECONCILE" : ", reconciles") +
          (result.status ? ` (${result.status})` : ""),
      }));
    } catch (err) {
      setPlan((prev) => ({ ...prev, [r.external_id]: errorMessage(err) }));
    } finally {
      setBusy(null);
    }
  }

  async function importIt(r: JlcStagedRow) {
    const ok = await dialog.confirm(
      `Import batch ${r.external_id} (invoice ${r.invoice_no || "—"}, ` +
        `$${r.total_amount ?? "?"})? It becomes one cost document whose lines are ` +
        `charged according to the decisions already recorded for its assembly orders. ` +
        `One reversible batch; it rolls back if the register stops balancing.`,
      { title: "Import this batch", confirmLabel: "Import" },
    );
    if (!ok) return;
    setBusy(r.external_id);
    try {
      await applyJlcDocument(r.external_id, false);
      load();
      onImported?.();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Import refused" });
    } finally {
      setBusy(null);
    }
  }

  async function importParts(o: JlcPartsOrder) {
    const ok = await dialog.confirm(
      `Import parts order ${o.pob} — ${o.lots} lots, $${o.paid_usd.toLocaleString()}? ` +
        `Each line becomes a purchase LOT that later draws bind to, priced at what was ` +
        `actually paid rather than what was quoted.` +
        (o.near_duplicate_document_id
          ? ` WARNING: document ${o.near_duplicate_document_id} (${o.near_duplicate_ref}) ` +
            `looks like the same purchase under a mistyped reference.`
          : ""),
      { title: "Import parts order", confirmLabel: "Import",
        tone: o.near_duplicate_document_id ? "danger" : "primary" },
    );
    if (!ok) return;
    setBusy(o.pob);
    try {
      await applyJlcParts(o.pob, false);
      load();
      onImported?.();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Import refused" });
    } finally {
      setBusy(null);
    }
  }

  if (loading && !rows) return <Spinner label="loading staged JLC batches" />;

  const all = rows ?? [];
  const pending = all.filter((r) => !r.document_id);
  const shown = onlyPending ? pending : all;
  // A zero-total batch is not a batch. Worth naming, because a document with no
  // value reconciles trivially and so is invisible to the register's own checks.
  const empty = pending.filter((r) => !r.total_amount);

  return (
    <div className="card">
      <h2 className="card-title">Staged JLCPCB batches</h2>
      <p className="card-subtitle">
        Sync only stages — it never writes a cost row. Importing is the separate,
        previewable, reversible step.
      </p>
      <ErrorBanner message={error} />

      <div className="toolbar">
        <span className="pill neutral">{all.length} staged</span>
        <span className={`pill ${pending.length ? "warn" : "ok"}`}>
          {pending.length} not imported
        </span>
        <span className="muted">
          ${pending.reduce((s, r) => s + (r.total_amount ?? 0), 0).toLocaleString()} awaiting
          import
        </span>
        {empty.length > 0 && (
          <span
            className="pill warn"
            title="Zero value. A document with no money in it reconciles trivially, so nothing in the register can flag it."
          >
            {empty.length} with no value
          </span>
        )}
        <label className="muted">
          <input
            type="checkbox"
            checked={onlyPending}
            onChange={(e) => setOnlyPending(e.target.checked)}
          />{" "}
          only not-yet-imported
        </label>
      </div>

      <div className="table-wrap">
        {shown.length === 0 ? (
          <p className="muted">Every staged batch has been imported.</p>
        ) : (
          <table className="data data-fixed jlc-staged-table">
            <thead>
              <tr>
                <th>batch</th>
                <th>invoice</th>
                <th>date</th>
                <th className="num">total</th>
                <th className="num">prepaid</th>
                <th>state</th>
                <th>import</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.external_id}>
                  <td className="mono" title={r.external_id}>
                    {r.external_id}
                  </td>
                  <td className="mono cell-desc" title={r.invoice_no}>
                    {r.invoice_no || "—"}
                  </td>
                  <td className="muted dim">{r.doc_date || "—"}</td>
                  <td className="num">
                    {r.total_amount == null ? (
                      <span className="dim">—</span>
                    ) : r.total_amount === 0 ? (
                      <span className="pill warn">$0</span>
                    ) : (
                      `$${r.total_amount.toLocaleString()}`
                    )}
                  </td>
                  <td className="num">
                    {r.presale_amount ? `$${r.presale_amount.toLocaleString()}` : "—"}
                  </td>
                  <td>
                    {r.document_id ? (
                      <span className="pill ok">document {r.document_id}</span>
                    ) : !r.has_payload ? (
                      <span className="pill err" title="The fetch failed — re-sync.">
                        no payload
                      </span>
                    ) : (
                      <span className="pill warn">staged</span>
                    )}
                  </td>
                  <td>
                    {!r.document_id && r.has_payload && (
                      <div className="btn-row">
                        <button
                          className="btn btn-sm"
                          disabled={busy === r.external_id}
                          onClick={() => preview(r)}
                        >
                          Preview
                        </button>
                        <button
                          className="btn btn-primary btn-sm"
                          disabled={busy === r.external_id}
                          onClick={() => importIt(r)}
                        >
                          Import
                        </button>
                      </div>
                    )}
                    {plan[r.external_id] && (
                      <div className="muted dim">{plan[r.external_id]}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h3 className="card-title">Parts orders (the lots)</h3>
      <p className="card-subtitle">
        Fetched live from JLCPCB, because sync stages assembly batches only. Each line of one
        of these documents IS a purchase lot — quantity and price taken from the ORDER page,
        never the invoice, which understates by JLC&apos;s sourcing fee.
      </p>
      <ErrorBanner message={partsErr} />
      {parts && (
        <div className="table-wrap">
          {parts.every((o) => o.document_id) ? (
            <p className="muted">
              All {parts.length} parts orders are imported ({parts.reduce((s, o) => s + o.lots, 0)}{" "}
              lots).
            </p>
          ) : (
            <table className="data data-fixed jlc-parts-table">
              <thead>
                <tr>
                  <th>order</th>
                  <th className="num">lots</th>
                  <th className="num">paid</th>
                  <th>state</th>
                  <th>import</th>
                </tr>
              </thead>
              <tbody>
                {parts
                  .filter((o) => !o.document_id)
                  .map((o) => (
                    <tr key={o.pob}>
                      <td className="mono">{o.pob}</td>
                      <td className="num">
                        {o.lots}
                        {o.cancelled_lots > 0 && (
                          <span className="muted dim" title="Cancelled sub-orders — no parts delivered.">
                            {" "}
                            ({o.cancelled_lots} cancelled)
                          </span>
                        )}
                      </td>
                      <td className="num">${o.paid_usd.toLocaleString()}</td>
                      <td>
                        {o.near_duplicate_document_id ? (
                          <span
                            className="pill err"
                            title={`Document ${o.near_duplicate_document_id} (${o.near_duplicate_ref}) looks like the same purchase under a mistyped reference.`}
                          >
                            maybe already doc {o.near_duplicate_document_id}
                          </span>
                        ) : (
                          <span className="pill warn">not imported</span>
                        )}
                      </td>
                      <td>
                        <button
                          className="btn btn-primary btn-sm"
                          disabled={busy === o.pob}
                          onClick={() => importParts(o)}
                        >
                          Import
                        </button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
