/** Costs — the same plan-vs-actual pattern as Materials, for processes and
 *  additional costs: what the Cost plan says each production step should cost,
 *  against what the invoices billed under that step, with supplier chips
 *  naming who billed it. Below it: the documents charged to this run, their
 *  lines, and the planned cost items with their final-price overrides.
 */
import { useState } from "react";
import {
  addDocumentLine,
  createDocument,
  deleteDocument,
  getRunActuals,
  getRunDocuments,
  voidCostLine,
  type RunEffective,
} from "../../api";
import { getCostSteps } from "../../api";
import DataTable from "../DataTable";
import { useDialog } from "../Dialog";
import Field, { CheckField } from "../Field";
import FoldSection, { StatChip } from "../FoldSection";
import { ErrorBanner, Spinner } from "../Ui";
import { StepSelect } from "../costs";
import { PART_STEPS } from "../invoices/InvoiceLinesTable";
import { amount as money, pln } from "../../format";
import { runAct } from "./runAct";
import { useLoad } from "../useLoad";

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
  /** The tab holds more than 4 cards (a crafted batch), so these cards fold at
   *  any length unless they hold a problem. */
  quiet?: boolean;
};

export default function RunCosts({
  quiet, projectId, runId, qty, runDate, effective, overrides, onOverride, onChanged,
}: Props) {
  const dialog = useDialog();
  const { data, error, setError, reload } = useLoad(
    (signal) => Promise.all([getRunDocuments(runId, signal), getRunActuals(runId, signal)]),
    [runId],
    { keep: true },
  );
  const docs = data?.[0] ?? null;
  const actuals = data?.[1] ?? null;
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
  // WHAT the position is, as a production step (decision 0047). It replaced a
  // `kind` select: the step is the finer answer and the coarse bucket is derived
  // from it on the server, so asking for both invited them to disagree.
  const [lineStep, setLineStep] = useState("pcba:general");
  const { data: stepCatalog } = useLoad(getCostSteps, []);
  const isStockStep = PART_STEPS.has(lineStep);
  const [lineLabel, setLineLabel] = useState("");
  const [lineMpn, setLineMpn] = useState("");
  const [lineQty, setLineQty] = useState("1");
  const [linePrice, setLinePrice] = useState("");
  const [linePerDevice, setLinePerDevice] = useState(false);

  const act = runAct(setBusy, setError, () => { reload(); onChanged(); });

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
        plan_key: lineStep,
        plan_kind: "cost",
        basis: linePerDevice ? "per_device" : "per_run",
        label: lineLabel.trim() || lineMpn.trim(),
        mpn: lineMpn.trim(),
        qty: Number(lineQty) || 0,
        unit_price: Number(linePrice) || 0,
        // A stock position stays in the pool (run_id null) and says so
        // (decision 0045); anything else is this batch's direct cost.
        allocate: isStockStep ? "pooled" : "none",
        run_id: isStockStep ? null : runId,
      });
      setLineLabel("");
      setLineMpn("");
      setLinePrice("");
    });

  const applyCostOverride = (key: string) => {
    const raw = overrideDrafts[key];
    const next = { ...(overrides ?? {}) } as Record<string, unknown>;
    if (raw === "" || raw == null) delete next[key];
    else next[key] = { price: Number(raw), currency: effective?.currency ?? "PLN" };
    onOverride(next);
  };

  if (!docs || !actuals) {
    return error ? <ErrorBanner message={error} /> : <Spinner label="Loading costs" />;
  }

  return (
    <>
      {error && <ErrorBanner message={error} />}

      {(actuals.steps ?? []).length > 0 && (
        <FoldSection
          title="Where the money goes: plan and billed, per step"
          count={(actuals.steps ?? []).length}
          // On a batch with no process this table IS the tab: it never folds there.
          limit={quiet ? -1 : Number.MAX_SAFE_INTEGER}
          foldKey={`run:${runId}:money-steps`}
          chips={(actuals.steps ?? []).some((st) => (st.delta_usd ?? 0) > 0.01) ? (
            <StatChip n={(actuals.steps ?? []).filter((st) => (st.delta_usd ?? 0) > 0.01).length} tone="warn">above plan</StatChip>
          ) : undefined}
        >
          <div className="table-wrap">
            <DataTable
              rows={actuals.steps ?? []}
              rowKey={(st) => st.key}
              columns={[
                { key: "step", label: "Step", width: 22, get: (st) => (st.key.startsWith("~") ? st.label : st.key),
                  title: (st) => st.label,
                  render: (st) => (st.key.startsWith("~") ? <span className="dim">{st.label}</span> : <span className="mono">{st.key}</span>) },
                { key: "planned", label: "Planned", width: 14, numeric: true, className: "muted", get: (st) => st.planned_usd,
                  render: (st) => (st.planned_usd == null ? "—" : pln(st.planned_usd, actuals.pln_per_usd)) },
                { key: "billed", label: "Billed", width: 14, numeric: true, get: (st) => st.actual_usd,
                  render: (st) => (st.actual_usd == null ? "—" : pln(st.actual_usd, actuals.pln_per_usd)) },
                { key: "delta", label: "Δ", width: 16, numeric: true, get: (st) => st.delta_usd,
                  render: (st) => (st.delta_usd == null ? (
                    <span className="dim">—</span>
                  ) : Math.abs(st.delta_usd) < 0.01 ? (
                    <span className="pill ok">0.00</span>
                  ) : (
                    <span className={`pill ${st.delta_usd > 0 ? "warn" : "neutral"}`}>
                      {st.delta_usd > 0 ? "+" : ""}{pln(st.delta_usd, actuals.pln_per_usd)}
                    </span>
                  )) },
                { key: "by", label: "Billed by", width: 34, interactive: false, get: () => "",
                  title: (st) => (st.sources ?? [])
                    .map((so) => `${so.supplier} ${so.doc_number} (${so.doc_date}): ${pln(so.amount_usd, actuals.pln_per_usd)}`)
                    .join(" · "),
                  render: (st) => (st.key === "parts:pool" ? (
                    <span className="dim">pool draws — see the Materials tab</span>
                  ) : (st.sources ?? []).length === 0 ? (
                    <span className="dim">—</span>
                  ) : (
                    <span className="state-facts">
                      {(st.sources ?? []).map((so) => (
                        <span key={so.document_id} className="pill neutral"
                              title={`${so.supplier} ${so.doc_number} — ${pln(so.amount_usd, actuals.pln_per_usd)} of this step`}>
                          {so.supplier || "?"} {so.doc_date}
                        </span>
                      ))}
                    </span>
                  )) },
              ]}
            />
          </div>
          <p className="muted">
            Planned figures come from the project&apos;s Cost plan; billed figures from the
            invoice positions tagged with each step. Hover a supplier chip for the document
            number and its share.
          </p>
        </FoldSection>
      )}

      {effective && effective.costs.length > 0 && (
        <FoldSection
          title="Planned cost items"
          count={effective.costs.length}
          limit={quiet ? -1 : undefined}
          foldKey={`run:${runId}:planned-costs`}
          chips={
            <>
              <StatChip n={money(effective.costs.reduce((a, c) => a + (c.dropped ? 0 : c.run_cost ?? 0), 0), effective.currency)}>run cost</StatChip>
              {effective.costs.some((c) => c.overridden) ? (
                <StatChip n={effective.costs.filter((c) => c.overridden).length} tone="warn">override</StatChip>
              ) : null}
              {effective.costs.some((c) => c.dropped) ? (
                <StatChip n={effective.costs.filter((c) => c.dropped).length}>dropped</StatChip>
              ) : null}
            </>
          }
        >
          <p className="muted dim">
            Priced from the Cost plan at the batch date. Type a final price and press Apply to
            override an item; blank + Apply clears it.
          </p>
          <div className="table-wrap">
            <DataTable
              rows={effective.costs}
              rowKey={(c) => c.key}
              rowClass={(c) => (c.dropped ? "row-dim" : "")}
              columns={[
                { key: "item", label: "Item", width: 50, get: (c) => c.label,
                  render: (c) => (
                    <>
                      {c.label}{" "}
                      <span className="muted">({c.basis === "per_run" ? "per run" : "per device"})</span>
                      {c.overridden ? <span className="pill warn">override</span> : null}
                    </>
                  ) },
                { key: "price", label: "Price", width: 14, numeric: true, get: (c) => c.price,
                  render: (c) => money(c.price, effective.currency) },
                { key: "run", label: "Run cost", width: 14, numeric: true, get: (c) => c.run_cost,
                  render: (c) => money(c.run_cost ?? null, effective.currency) },
                { key: "override", label: "Final price override", width: 22, numeric: true, interactive: false, get: () => "",
                  render: (c) => (
                    <>
                      <input
                        className="text num-input"
                        placeholder="price"
                        value={overrideDrafts[c.key] ?? ""}
                        onChange={(e) => setOverrideDrafts({ ...overrideDrafts, [c.key]: e.target.value })}
                      />{" "}
                      <button className="btn btn-sm" onClick={() => applyCostOverride(c.key)}>Apply</button>
                    </>
                  ) },
              ]}
            />
          </div>
        </FoldSection>
      )}

      <FoldSection
        title="Documents on this batch"
        count={docs.length}
        limit={quiet && !docs.some((d) => d.total_amount !== null && !d.reconciled) ? -1 : undefined}
        foldKey={`run:${runId}:documents`}
        forceOpen={showDoc || openDoc !== null}
        chips={docs.length ? (
          <>
            {docs.some((d) => d.total_amount !== null && !d.reconciled) ? (
              <StatChip n={docs.filter((d) => d.total_amount !== null && !d.reconciled).length} tone="err">total does not match</StatChip>
            ) : null}
            <StatChip n={docs.reduce((a, d) => a + d.line_count, 0).toLocaleString()}>lines</StatChip>
            {[...new Set(docs.map((d) => d.supplier || "no supplier"))].slice(0, 2).map((s) => (
              <StatChip key={s} n={docs.filter((d) => (d.supplier || "no supplier") === s).length}>{s}</StatChip>
            ))}
          </>
        ) : undefined}
        actions={
          <button className="btn btn-sm btn-primary" onClick={() => setShowDoc((v) => !v)}>
            {showDoc ? "Cancel" : "Add invoice / document"}
          </button>
        }
      >
        {actuals.qty_good_source === "typed" && (
          <p className="muted">
            Per-device figures divide by {actuals.qty_good ?? qty} — the quantity typed on the
            batch, because no device of it was ever recorded. A batch the flasher recorded
            divides by the devices that passed instead.
          </p>
        )}

        {showDoc && (
          <div className="card pad edit-card">
            <div className="field-grid">
              <Field label="Supplier">
                <input className="text" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
              </Field>
              <Field label="Document no.">
                <input className="text" value={docNumber} placeholder="invoice number"
                  onChange={(e) => setDocNumber(e.target.value)} />
              </Field>
              <Field label="Date">
                <input className="text" value={docDate} placeholder="YYYY-MM-DD"
                  onChange={(e) => setDocDate(e.target.value)} />
              </Field>
              <Field label="Currency">
                <input className="text" value={currency} onChange={(e) => setCurrency(e.target.value)} />
              </Field>
              <Field label="Total as printed">
                <input className="text" value={docTotal} placeholder="optional, reconciles lines"
                  onChange={(e) => setDocTotal(e.target.value)} />
              </Field>
              <CheckField checked={forThisRun} onChange={setForThisRun}>Belongs to this batch</CheckField>
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
            <DataTable
              rows={docs}
              rowKey={(d) => d.id}
              rowClass={(d) => (openDoc === d.id ? "row-selected" : "")}
              columns={[
                { key: "supplier", label: "Supplier", width: 20, get: (d) => d.supplier || "—" },
                { key: "number", label: "Number", width: 22, className: "mono", get: (d) => d.doc_number || "—",
                  title: (d) => d.external_id || d.doc_number },
                { key: "date", label: "Date", width: 12, get: (d) => d.doc_date || "—" },
                { key: "lines", label: "Lines", width: 7, numeric: true, get: (d) => d.line_count },
                { key: "sum", label: "Sum", width: 14, numeric: true, get: (d) => d.lines_total,
                  render: (d) => money(d.lines_total, d.currency) },
                { key: "printed", label: "Printed", width: 14, numeric: true, get: (d) => d.total_amount,
                  render: (d) => (d.total_amount === null ? (
                    <span className="muted">—</span>
                  ) : d.reconciled ? (
                    money(d.total_amount, d.currency)
                  ) : (
                    <span className="pill err" title="entered total does not match the sum of lines">
                      {money(d.total_amount, d.currency)}
                    </span>
                  )) },
                { key: "act", label: "", width: "142px", interactive: false, className: "ctr", get: () => "",
                  render: (d) => (
                    <>
                      <button className="btn btn-sm" onClick={() => setOpenDoc(openDoc === d.id ? null : d.id)}>
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
                    </>
                  ) },
              ]}
            />
          </div>
        )}

        {openDoc !== null && (() => {
          const d = docs.find((x) => x.id === openDoc);
          if (!d) return null;
          return (
            <div className="card pad">
              <FoldSection
                bare
                title={`Lines — ${d.supplier} ${d.doc_number}`}
                count={(d.lines ?? []).filter((li) => !li.voided).length}
                foldKey={`run:${runId}:doc:${d.id}:lines`}
                chips={<StatChip n={money(d.lines_total, d.currency)}>sum</StatChip>}
              >
              {(d.lines ?? []).filter((li) => !li.voided).length === 0 ? (
                <p className="muted">No lines yet.</p>
              ) : (
                <div className="table-wrap">
                  <DataTable
                    rows={(d.lines ?? []).filter((li) => !li.voided)}
                    rowKey={(li) => li.id}
                    columns={[
                      { key: "kind", label: "Kind", width: 11, get: (li) => li.kind,
                        render: (li) => <span className="badge">{li.kind}</span> },
                      { key: "label", label: "Label", width: 22, get: (li) => li.label || "—" },
                      { key: "mpn", label: "MPN", width: 19, className: "mono", get: (li) => li.mpn || "—" },
                      { key: "qty", label: "Qty", width: 8, numeric: true, get: (li) => li.qty,
                        title: (li) => (li.basis === "per_device"
                          ? `${li.qty} per device x ${li.qty_effective && li.qty ? Math.round(li.qty_effective / li.qty) : "?"} units`
                          : undefined),
                        render: (li) => (li.basis === "per_device" && li.qty_effective ? `${li.qty} → ${li.qty_effective}` : li.qty) },
                      { key: "unit", label: "Unit", width: 10, numeric: true, get: (li) => li.unit_price },
                      { key: "total", label: "Total", width: 12, numeric: true, get: (li) => li.line_total,
                        render: (li) => money(li.line_total, li.currency) },
                      { key: "where", label: "Where", width: 11, className: "muted",
                        get: (li) => (li.kind === "part" && li.run_id === null
                          ? "cost pool" : li.basis === "per_device" ? "batch · per device" : "batch") },
                      { key: "act", label: "", width: 7, interactive: false, className: "ctr", get: () => "",
                        render: (li) => (
                          <button className="btn btn-sm btn-danger" disabled={busy}
                            onClick={async () => {
                              const ok = await dialog.confirm(`Void "${li.label || li.mpn}"? Its money leaves this batch.`,
                                { title: "Void line", confirmLabel: "Void", tone: "danger" });
                              if (ok) void act(() => voidCostLine(li.id));
                            }}>Void</button>
                        ) },
                    ]}
                  />
                </div>
              )}
              </FoldSection>
              <div className="field-grid">
                <Field label="What it is">
                  <StepSelect
                    catalog={stepCatalog}
                    className="text mono"
                    value={lineStep}
                    onChange={setLineStep}
                  />
                </Field>
                <Field label="Label">
                  <input className="text" value={lineLabel}
                    onChange={(e) => setLineLabel(e.target.value)} />
                </Field>
                <Field label="MPN">
                  <input className="text" value={lineMpn}
                    onChange={(e) => setLineMpn(e.target.value)} />
                </Field>
                <Field label="Qty">
                  <input className="text" value={lineQty}
                    onChange={(e) => setLineQty(e.target.value)} />
                </Field>
                <Field label="Unit price">
                  <input className="text" value={linePrice}
                    onChange={(e) => setLinePrice(e.target.value)} />
                </Field>
                {!isStockStep && (
                  <CheckField checked={linePerDevice} onChange={setLinePerDevice}>Per device (× {qty})</CheckField>
                )}
              </div>
              <p className="muted">
                {isStockStep
                  ? "Stock positions go into the component cost pool — batches draw from it on the Materials tab."
                  : "This lands directly on this batch's cost."}
              </p>
              <div className="btn-row">
                <button className="btn btn-sm btn-primary" disabled={busy || !linePrice.trim()}
                  onClick={() => submitLine(d.id)}>Add line</button>
              </div>
            </div>
          );
        })()}
      </FoldSection>
    </>
  );
}
