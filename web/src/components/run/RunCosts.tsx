/** Costs — the same plan-vs-actual pattern as Materials, for processes and
 *  additional costs: what the Cost plan says each production step should cost,
 *  against what the invoices billed under that step, with supplier chips
 *  naming who billed it. Below it: the documents charged to this run, their
 *  lines, and the planned cost items with their final-price overrides.
 */
import { useCallback, useEffect, useState } from "react";
import {
  addDocumentLine,
  createDocument,
  deleteDocument,
  errorMessage,
  getRunActuals,
  getRunDocuments,
  isAbortError,
  voidCostLine,
  type CostLineKind,
  type RunActuals,
  type RunCostDocumentRow,
  type RunEffective,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";
import { COST_LINE_KINDS as KINDS } from "../costs";
import { amount as money, plain } from "../../format";

type Props = {
  projectId: number;
  runId: number;
  /** run.qty — used as the fallback denominator when qty_good is unset */
  qty: number;
  runDate: string;
  effective: RunEffective | null;
  overrides: Record<string, unknown> | undefined;
  onOverride: (overrides: Record<string, unknown>) => void;
  onChanged: () => void;
};

export default function RunCosts({
  projectId, runId, qty, runDate, effective, overrides, onOverride, onChanged,
}: Props) {
  const dialog = useDialog();
  const [docs, setDocs] = useState<RunCostDocumentRow[] | null>(null);
  const [actuals, setActuals] = useState<RunActuals | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showDoc, setShowDoc] = useState(false);
  const [openDoc, setOpenDoc] = useState<number | null>(null);
  const [overrideDrafts, setOverrideDrafts] = useState<Record<string, string>>({});

  // new-document draft
  const [supplier, setSupplier] = useState("JLCPCB");
  const [docNumber, setDocNumber] = useState("");
  const [docDate, setDocDate] = useState(runDate || "");
  const [currency, setCurrency] = useState("USD");
  const [docTotal, setDocTotal] = useState("");
  const [forThisRun, setForThisRun] = useState(true);

  // new-line draft
  const [lineKind, setLineKind] = useState<CostLineKind>("assembly");
  const [lineLabel, setLineLabel] = useState("");
  const [lineMpn, setLineMpn] = useState("");
  const [lineQty, setLineQty] = useState("1");
  const [linePrice, setLinePrice] = useState("");
  const [linePerDevice, setLinePerDevice] = useState(false);

  const reload = useCallback((signal?: AbortSignal) => {
    Promise.all([getRunDocuments(runId, signal), getRunActuals(runId, signal)])
      .then(([d, a]) => {
        setDocs(d);
        setActuals(a);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  }, [runId]);

  useEffect(() => {
    const ac = new AbortController();
    reload(ac.signal);
    return () => ac.abort();
  }, [reload]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      reload();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitDoc = () =>
    act(async () => {
      await createDocument(projectId, {
        supplier: supplier.trim(),
        doc_number: docNumber.trim(),
        doc_date: docDate.trim(),
        currency: currency.trim().toUpperCase() || "USD",
        total_amount: docTotal.trim() ? Number(docTotal) : null,
        run_id: forThisRun ? runId : null,
      });
      setShowDoc(false);
      setDocNumber("");
      setDocTotal("");
    });

  const submitLine = (docId: number) =>
    act(async () => {
      await addDocumentLine(docId, {
        kind: lineKind,
        basis: linePerDevice ? "per_device" : "per_run",
        label: lineLabel.trim() || lineMpn.trim(),
        mpn: lineMpn.trim(),
        qty: Number(lineQty) || 0,
        unit_price: Number(linePrice) || 0,
        // A part line stays in the pool (run_id null); anything else is this
        // batch's direct cost.
        run_id: lineKind === "part" ? null : runId,
      });
      setLineLabel("");
      setLineMpn("");
      setLinePrice("");
    });

  const applyCostOverride = (key: string) => {
    const raw = overrideDrafts[key];
    const next = { ...(overrides ?? {}) } as Record<string, unknown>;
    if (raw === "" || raw == null) delete next[key];
    else next[key] = { price: Number(raw) };
    onOverride(next);
  };

  if (!docs || !actuals) {
    return error ? <ErrorBanner message={error} /> : <Spinner label="Loading costs" />;
  }

  return (
    <>
      {error && <ErrorBanner message={error} />}

      {(actuals.steps ?? []).length > 0 && (
        <div className="card pad">
          <h2 className="card-title">Where the money goes — plan vs billed, per step (USD)</h2>
          <div className="table-wrap">
            <table className="data data-fixed run-steps-table">
              <thead>
                <tr>
                  <th>Step</th>
                  <th className="num">Planned</th>
                  <th className="num">Billed</th>
                  <th className="num">Δ</th>
                  <th>Billed by</th>
                </tr>
              </thead>
              <tbody>
                {(actuals.steps ?? []).map((st) => (
                  <tr key={st.key}>
                    <td title={st.label}>
                      <span className="mono">{st.key.startsWith("~") ? "" : st.key}</span>
                      {st.key.startsWith("~") ? <span className="dim">{st.label}</span> : null}
                    </td>
                    <td className="num muted">{st.planned_usd == null ? "—" : plain(st.planned_usd)}</td>
                    <td className="num">{st.actual_usd == null ? "—" : plain(st.actual_usd)}</td>
                    <td className="num">
                      {st.delta_usd == null ? (
                        <span className="dim">—</span>
                      ) : Math.abs(st.delta_usd) < 0.01 ? (
                        <span className="pill ok">0.00</span>
                      ) : (
                        <span className={`pill ${st.delta_usd > 0 ? "warn" : "neutral"}`}>
                          {st.delta_usd > 0 ? "+" : ""}{plain(st.delta_usd)}
                        </span>
                      )}
                    </td>
                    <td title={(st.sources ?? [])
                        .map((so) => `${so.supplier} ${so.doc_number} (${so.doc_date}): $${so.amount_usd?.toFixed(2)}`)
                        .join(" · ")}>
                      {st.key === "parts:pool" ? (
                        <span className="dim">pool draws — see the Materials tab</span>
                      ) : (st.sources ?? []).length === 0 ? (
                        <span className="dim">—</span>
                      ) : (
                        (st.sources ?? []).map((so) => (
                          <span key={so.document_id} className="pill neutral"
                                title={`${so.supplier} ${so.doc_number} — $${so.amount_usd?.toFixed(2)} of this step`}>
                            {so.supplier || "?"} {so.doc_date}
                          </span>
                        ))
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            Planned figures come from the project&apos;s Cost plan; billed figures from the
            invoice positions tagged with each step. Hover a supplier chip for the document
            number and its share.
          </p>
        </div>
      )}

      {effective && effective.costs.length > 0 && (
        <div className="card pad">
          <h2 className="card-title">Planned cost items (this batch)</h2>
          <p className="card-subtitle">
            Priced from the Cost plan at the run date. Type a final price and press Apply to
            override an item; blank + Apply clears it.
          </p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Item</th>
                  <th className="num">Price</th>
                  <th className="num">Run cost</th>
                  <th className="num">Final price override</th>
                </tr>
              </thead>
              <tbody>
                {effective.costs.map((c) => (
                  <tr key={c.key} className={c.dropped ? "row-dim" : ""}>
                    <td className="cell-desc">
                      {c.label}{" "}
                      <span className="muted">
                        ({c.basis === "per_run" ? "per run" : "per device"})
                      </span>
                      {c.overridden ? <span className="pill warn">override</span> : null}
                    </td>
                    <td className="num">{money(c.price, effective.currency)}</td>
                    <td className="num">{money(c.run_cost ?? null, effective.currency)}</td>
                    <td className="num nowrap">
                      <input
                        className="text num-input"
                        placeholder="price"
                        value={overrideDrafts[c.key] ?? ""}
                        onChange={(e) =>
                          setOverrideDrafts({ ...overrideDrafts, [c.key]: e.target.value })
                        }
                      />{" "}
                      <button className="btn btn-sm" onClick={() => applyCostOverride(c.key)}>
                        Apply
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card pad">
        <h2 className="card-title">Documents on this batch</h2>
        {actuals.qty_good === null && (
          <p className="muted">
            Per-device figures use the planned quantity ({qty}) — set Units good on the
            Overview tab for a real yield-based figure.
          </p>
        )}
        <div className="btn-row">
          <button className="btn btn-sm btn-primary" onClick={() => setShowDoc((v) => !v)}>
            {showDoc ? "Cancel" : "Add invoice / document"}
          </button>
        </div>

        {showDoc && (
          <div className="card pad edit-card">
            <div className="edit-grid">
              <label>Supplier
                <input className="text" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
              </label>
              <label>Document no.
                <input className="text" value={docNumber} placeholder="invoice number"
                  onChange={(e) => setDocNumber(e.target.value)} />
              </label>
              <label>Date
                <input className="text" value={docDate} placeholder="YYYY-MM-DD"
                  onChange={(e) => setDocDate(e.target.value)} />
              </label>
              <label>Currency
                <input className="text" value={currency} onChange={(e) => setCurrency(e.target.value)} />
              </label>
              <label>Total as printed
                <input className="text" value={docTotal} placeholder="optional, reconciles lines"
                  onChange={(e) => setDocTotal(e.target.value)} />
              </label>
              <label>
                <input type="checkbox" checked={forThisRun}
                  onChange={(e) => setForThisRun(e.target.checked)} />{" "}
                Belongs to this batch
              </label>
            </div>
            <div className="btn-row">
              <button className="btn btn-sm btn-primary" disabled={busy || !supplier.trim()}
                onClick={submitDoc}>Create</button>
            </div>
          </div>
        )}

        {docs.length === 0 ? (
          <p className="muted">No documents on this batch yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data data-fixed run-docs-table">
              <thead>
                <tr>
                  <th>Supplier</th>
                  <th>Number</th>
                  <th>Date</th>
                  <th>Lines</th>
                  <th>Sum</th>
                  <th>Printed</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id} className={openDoc === d.id ? "row-selected" : ""}>
                    <td title={d.supplier}>{d.supplier || "—"}</td>
                    <td className="mono" title={d.external_id || d.doc_number}>
                      {d.doc_number || "—"}
                    </td>
                    <td>{d.doc_date || "—"}</td>
                    <td className="num">{d.line_count}</td>
                    <td className="num">{money(d.lines_total, d.currency)}</td>
                    <td className="num">
                      {d.total_amount === null ? (
                        <span className="muted">—</span>
                      ) : d.reconciled ? (
                        money(d.total_amount, d.currency)
                      ) : (
                        <span className="pill err" title="entered total does not match the sum of lines">
                          {money(d.total_amount, d.currency)}
                        </span>
                      )}
                    </td>
                    <td className="ctr">
                      <button className="btn btn-sm"
                        onClick={() => setOpenDoc(openDoc === d.id ? null : d.id)}>
                        {openDoc === d.id ? "Close" : "Lines"}
                      </button>{" "}
                      <button className="btn btn-sm btn-danger" disabled={busy}
                        onClick={async () => {
                          if (!(await dialog.confirm(
                            `Delete document ${d.supplier} ${d.doc_number}?`,
                            { title: "Delete document", confirmLabel: "Delete", tone: "danger" },
                          ))) return;
                          void act(() => deleteDocument(d.id, true));
                        }}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {openDoc !== null && (() => {
          const d = docs.find((x) => x.id === openDoc);
          if (!d) return null;
          return (
            <div className="card pad">
              <div className="card-subtitle">
                Lines — {d.supplier} {d.doc_number}
              </div>
              {(d.lines ?? []).filter((li) => !li.voided).length === 0 ? (
                <p className="muted">No lines yet.</p>
              ) : (
                <div className="table-wrap">
                  <table className="data data-fixed run-lines-table">
                    <thead>
                      <tr>
                        <th>Kind</th>
                        <th>Label</th>
                        <th>MPN</th>
                        <th>Qty</th>
                        <th>Unit</th>
                        <th>Total</th>
                        <th>Where</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {(d.lines ?? []).filter((li) => !li.voided).map((li) => (
                        <tr key={li.id}>
                          <td><span className="badge">{li.kind}</span></td>
                          <td title={li.label}>{li.label || "—"}</td>
                          <td className="mono" title={li.mpn}>{li.mpn || "—"}</td>
                          <td className="num" title={li.basis === "per_device"
                            ? `${li.qty} per device x ${li.qty_effective && li.qty
                                ? Math.round(li.qty_effective / li.qty) : "?"} units`
                            : undefined}>
                            {li.basis === "per_device" && li.qty_effective
                              ? `${li.qty} → ${li.qty_effective}`
                              : li.qty}
                          </td>
                          <td className="num">{li.unit_price}</td>
                          <td className="num">{money(li.line_total, li.currency)}</td>
                          <td className="muted">
                            {li.kind === "part" && li.run_id === null
                              ? "cost pool"
                              : li.basis === "per_device" ? "run · per device" : "run"}
                          </td>
                          <td className="ctr">
                            <button className="btn btn-sm btn-danger" disabled={busy}
                              onClick={() => void act(() => voidCostLine(li.id))}>Void</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="edit-grid">
                <label>Kind
                  <select className="text" value={lineKind}
                    onChange={(e) => setLineKind(e.target.value as CostLineKind)}>
                    {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                  </select>
                </label>
                <label>Label
                  <input className="text" value={lineLabel}
                    onChange={(e) => setLineLabel(e.target.value)} />
                </label>
                <label>MPN
                  <input className="text" value={lineMpn}
                    onChange={(e) => setLineMpn(e.target.value)} />
                </label>
                <label>Qty
                  <input className="text" value={lineQty}
                    onChange={(e) => setLineQty(e.target.value)} />
                </label>
                <label>Unit price
                  <input className="text" value={linePrice}
                    onChange={(e) => setLinePrice(e.target.value)} />
                </label>
                {lineKind !== "part" && (
                  <label>
                    <input type="checkbox" checked={linePerDevice}
                      onChange={(e) => setLinePerDevice(e.target.checked)} />{" "}
                    Per device (× {qty})
                  </label>
                )}
              </div>
              <p className="muted">
                {lineKind === "part"
                  ? "Part lines go into the component cost pool — batches draw from it on the Materials tab."
                  : "This lands directly on this batch's cost."}
              </p>
              <div className="btn-row">
                <button className="btn btn-sm btn-primary" disabled={busy || !linePrice.trim()}
                  onClick={() => submitLine(d.id)}>Add line</button>
              </div>
            </div>
          );
        })()}
      </div>
    </>
  );
}
