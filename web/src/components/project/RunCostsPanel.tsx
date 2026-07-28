import { useCallback, useEffect, useState } from "react";

import {
  addDocumentLine,
  addRunConsumption,
  addStockAdjustment,
  consumeFromBom,
  createDocument,
  deleteConsumption,
  deleteDocument,
  errorMessage,
  getRunActuals,
  getRunConsumption,
  getRunDocuments,
  isAbortError,
  voidCostLine,
  type ConsumptionRow,
  type CostLineKind,
  type RunActuals,
  type RunCostDocumentRow,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";

const KINDS: CostLineKind[] = [
  "part", "fab", "assembly", "tooling", "freight",
  "duty", "tax", "rework", "packaging", "service", "other",
];

type Props = {
  projectId: number;
  runId: number;
  /** run.qty — used as the fallback denominator when qty_good is unset */
  qty: number;
  runDate: string;
  hasSnapshot: boolean;
};

function money(v: number | null | undefined, currency: string): string {
  if (v === null || v === undefined) return "—";
  return `${v.toFixed(2)} ${currency}`;
}

/**
 * Post-factum costs for one production run: supplier documents (invoices),
 * what the run drew from the component cost pool, and attrition.
 *
 * A `part` line with no run feeds the pool — invoices are stockpile
 * replenishment, so a purchase is never booked straight onto a batch. Any other
 * kind is a direct cost of this run.
 */
export default function RunCostsPanel({ projectId, runId, qty, runDate, hasSnapshot }: Props) {
  const dialog = useDialog();
  const [docs, setDocs] = useState<RunCostDocumentRow[] | null>(null);
  const [actuals, setActuals] = useState<RunActuals | null>(null);
  const [consumption, setConsumption] = useState<ConsumptionRow[] | null>(null);
  const [showLots, setShowLots] = useState(
    () => localStorage.getItem("costs.showLots") === "1",
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showDoc, setShowDoc] = useState(false);
  const [openDoc, setOpenDoc] = useState<number | null>(null);

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

  // consumption + attrition drafts
  const [consMpn, setConsMpn] = useState("");
  const [consQty, setConsQty] = useState("");
  const [lossMpn, setLossMpn] = useState("");
  const [lossQty, setLossQty] = useState("");

  const reload = useCallback((signal?: AbortSignal) => {
    Promise.all([
      getRunDocuments(runId, signal),
      getRunActuals(runId, signal),
      getRunConsumption(runId, signal),
    ])
      .then(([d, a, c]) => {
        setDocs(d);
        setActuals(a);
        setConsumption(c);
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

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitDoc = () =>
    run(async () => {
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
    run(async () => {
      await addDocumentLine(docId, {
        kind: lineKind,
        basis: linePerDevice ? "per_device" : "per_run",
        label: lineLabel.trim() || lineMpn.trim(),
        mpn: lineMpn.trim(),
        qty: Number(lineQty) || 0,
        unit_price: Number(linePrice) || 0,
        // A part line stays in the pool (run_id null); anything else is this
        // run's direct cost.
        run_id: lineKind === "part" ? null : runId,
      });
      setLineLabel("");
      setLineMpn("");
      setLinePrice("");
    });

  const cur = actuals?.currency ?? "USD";
  const denom = actuals?.qty_good ?? qty;

  return (
    <>
      <div className="card-subtitle">Costs &amp; invoices (post factum)</div>
      {error && <ErrorBanner message={error} />}
      {!docs || !actuals ? (
        <Spinner label="Loading actual costs" />
      ) : (
        <>
          <div className="table-wrap">
            <table className="data data-fixed run-actuals-table">
              <thead>
                <tr>
                  <th>Components drawn</th>
                  <th>Direct costs</th>
                  <th>Attrition</th>
                  <th>Actual total</th>
                  <th>Per device</th>
                  <th>Planned</th>
                  <th>Δ</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="num">{money(actuals.components, cur)}</td>
                  <td className="num" title={Object.entries(actuals.by_kind)
                    .map(([k, v]) => `${k}: ${v}`).join(" · ")}>
                    {money(actuals.direct, cur)}
                  </td>
                  <td className="num">{money(actuals.attrition, cur)}</td>
                  <td className="num"><b>{money(actuals.total, cur)}</b></td>
                  <td className="num" title={`over ${denom} units`}>
                    {money(actuals.per_device, cur)}
                  </td>
                  <td className="num muted">{money(actuals.planned_total, cur)}</td>
                  <td className="num">
                    {actuals.delta === null ? (
                      <span className="muted">no baseline</span>
                    ) : (
                      <span className={`pill ${actuals.delta > 0 ? "warn" : "ok"}`}>
                        {actuals.delta > 0 ? "+" : ""}{actuals.delta.toFixed(2)}
                        {actuals.delta_pct !== null && ` (${actuals.delta_pct.toFixed(1)}%)`}
                      </span>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          {(actuals.steps ?? []).length > 0 && (
            <>
              <h4 className="card-subtitle">Where the money goes — plan vs billed, per production step (USD)</h4>
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
                        <td className="num muted">{st.planned_usd == null ? "—" : st.planned_usd.toFixed(2)}</td>
                        <td className="num">{st.actual_usd == null ? "—" : st.actual_usd.toFixed(2)}</td>
                        <td className="num">
                          {st.delta_usd == null ? (
                            <span className="dim">—</span>
                          ) : Math.abs(st.delta_usd) < 0.01 ? (
                            <span className="pill ok">0.00</span>
                          ) : (
                            <span className={`pill ${st.delta_usd > 0 ? "warn" : "neutral"}`}>
                              {st.delta_usd > 0 ? "+" : ""}{st.delta_usd.toFixed(2)}
                            </span>
                          )}
                        </td>
                        <td title={(st.sources ?? [])
                            .map((so) => `${so.supplier} ${so.doc_number} (${so.doc_date}): $${so.amount_usd?.toFixed(2)}`)
                            .join(" · ")}>
                          {st.key === "parts:pool" ? (
                            <span className="dim">pool draws — purchase invoices in Parts stock</span>
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
                Billed figures come from the invoice positions tagged with each step; hover a
                supplier chip for the document number and its share.
              </p>
            </>
          )}
          {actuals.qty_good === null && (
            <p className="muted">
              Per-device uses the planned quantity ({qty}) — set the run&apos;s good-unit count
              for a real yield-based figure.
            </p>
          )}
          {actuals.unknown_rates.length > 0 && (
            <div className="banner-warn">
              No stored FX rate for {actuals.unknown_rates.join(", ")} — those amounts are
              converted 1:1.
            </div>
          )}

          <div className="btn-row">
            <button className="btn btn-sm btn-primary" onClick={() => setShowDoc((v) => !v)}>
              {showDoc ? "Cancel" : "Add invoice / document"}
            </button>
            {hasSnapshot && (
              <button className="btn btn-sm" disabled={busy}
                onClick={() => run(async () => {
                  const r = await consumeFromBom(runId);
                  if (r.unpriced.length) {
                    await dialog.alert(
                      `${r.created} lines drawn for ${r.volume} units. ` +
                      `${r.unpriced.length} part(s) had nothing in the pool and were costed at 0: ` +
                      r.unpriced.slice(0, 12).join(", "),
                      { title: "Drawn from pool, with gaps" },
                    );
                  }
                })}>
                Draw BOM from pool
              </button>
            )}
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
                  Belongs to this run
                </label>
              </div>
              <div className="btn-row">
                <button className="btn btn-sm btn-primary" disabled={busy || !supplier.trim()}
                  onClick={submitDoc}>Create</button>
              </div>
            </div>
          )}

          {docs.length === 0 ? (
            <p className="muted">No documents on this run yet.</p>
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
                            run(() => deleteDocument(d.id, true));
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
                                onClick={() => run(() => voidCostLine(li.id))}>Void</button>
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
                    ? "Part lines go into the component cost pool — runs draw from it below."
                    : "This lands directly on this run's cost."}
                </p>
                <div className="btn-row">
                  <button className="btn btn-sm btn-primary" disabled={busy || !linePrice.trim()}
                    onClick={() => submitLine(d.id)}>Add line</button>
                </div>
              </div>
            );
          })()}

          <div className="card-subtitle">Drawn from the pool ({consumption?.length ?? 0})</div>
          {/* A global toggle, NOT per-row disclosure: off shows one averaged row
              per part, on replaces that row with one flat row per purchase lot.
              The parent's unit cost is the qty-weighted average of its lots, so
              switching can never change a total. */}
          <label className="muted">
            <input
              type="checkbox"
              checked={showLots}
              onChange={(e) => {
                setShowLots(e.target.checked);
                localStorage.setItem("costs.showLots", e.target.checked ? "1" : "");
              }}
            />{" "}
            show purchase lots
          </label>
          {consumption && consumption.length > 0 && (
            <div className="table-wrap">
              <table className="data data-fixed run-cons-table">
                <thead>
                  <tr>
                    <th>Part</th>
                    <th>Qty</th>
                    <th>Unit cost (USD)</th>
                    <th>Total (USD)</th>
                    <th>Basis</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {consumption.flatMap((c) => {
                    const part = c.mpn || c.lcsc || `#${c.component_id ?? "?"}`;
                    const basisPill = (
                      <span className={`pill ${c.basis === "measured" ? "ok"
                        : c.basis === "allocated" ? "warn" : "neutral"}`}>{c.basis}</span>
                    );
                    // Only split when there is more than one lot: a single-lot
                    // draw would otherwise render an identical duplicate row.
                    if (!showLots || c.lots.length < 2) {
                      return [
                        <tr key={c.id}>
                          <td className="mono" title={c.mpn || c.lcsc}>{part}</td>
                          <td className="num">{c.qty}</td>
                          <td className="num">{c.unit_cost_usd.toFixed(6)}</td>
                          <td className="num">{c.total_usd.toFixed(4)}</td>
                          <td>{basisPill}</td>
                          <td className="ctr">
                            <button className="btn btn-sm btn-danger" disabled={busy}
                              onClick={() => run(() => deleteConsumption(c.id))}>Remove</button>
                          </td>
                        </tr>,
                      ];
                    }
                    return c.lots.map((lot, i) => (
                      <tr key={`${c.id}-${lot.id}`}>
                        <td className="mono" title={`${part} — lot ${lot.ext_ref}`}>
                          {part} <span className="dim">/ {lot.purchase_order || lot.ext_ref}</span>
                        </td>
                        <td className="num">{lot.qty}</td>
                        <td className="num">{lot.unit_cost_usd.toFixed(6)}</td>
                        <td className="num">{lot.total_usd.toFixed(4)}</td>
                        <td>
                          <span className={`pill ${lot.source === "reported" ? "ok" : "warn"}`}>
                            {lot.source}
                          </span>
                        </td>
                        <td className="ctr">
                          {i === 0 && (
                            <button className="btn btn-sm btn-danger" disabled={busy}
                              onClick={() => run(() => deleteConsumption(c.id))}>Remove</button>
                          )}
                        </td>
                      </tr>
                    ));
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="edit-grid">
            <label>Draw part (MPN)
              <input className="text" value={consMpn} onChange={(e) => setConsMpn(e.target.value)} />
            </label>
            <label>Quantity
              <input className="text" value={consQty} onChange={(e) => setConsQty(e.target.value)} />
            </label>
            <label>Lost part (MPN)
              <input className="text" value={lossMpn} onChange={(e) => setLossMpn(e.target.value)} />
            </label>
            <label>Quantity lost
              <input className="text" value={lossQty} onChange={(e) => setLossQty(e.target.value)} />
            </label>
          </div>
          <div className="btn-row">
            <button className="btn btn-sm" disabled={busy || !consMpn.trim() || !consQty.trim()}
              onClick={() => run(async () => {
                await addRunConsumption(runId, {
                  mpn: consMpn.trim(), qty: Number(consQty) || 0, basis: "manual",
                });
                setConsMpn("");
                setConsQty("");
              })}>Draw from pool</button>
            <button className="btn btn-sm btn-danger" disabled={busy || !lossMpn.trim() || !lossQty.trim()}
              onClick={() => run(async () => {
                await addStockAdjustment(projectId, {
                  mpn: lossMpn.trim(), qty_delta: -Math.abs(Number(lossQty) || 0),
                  reason: "attrition", charge_run_id: runId, adjusted_at: runDate,
                  note: "lost in production",
                });
                setLossMpn("");
                setLossQty("");
              })}>Write off as attrition</button>
          </div>
          <p className="muted">
            Attrition is charged to this run, so its per-device cost carries the real loss.
            Pool quantities exist to split invoice cost — they are not expected to match
            JLCPCB&apos;s stock exactly.
          </p>
        </>
      )}
    </>
  );
}
