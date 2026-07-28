/** Invoices — where supplier documents are entered and their positions handed
 *  out to runs and projects.
 *
 *  The point of a dedicated view (user decision 2026-07-27): one invoice often
 *  pays for several batches, so the unit of assignment is the POSITION, not the
 *  document. A position can be split into shares charged to different runs, and
 *  split again into a supplier's own sub-fees. A line with shares becomes a
 *  header worth zero — the shares carry the money — so nothing is double counted.
 *
 *  The summary at the top is the "money is not disappearing anywhere" check:
 *  every document's total lands in exactly one of runs / projects / pool /
 *  unassigned / residual, and the component pool must balance against what has
 *  been drawn from it.
 */
import { Fragment, useCallback, useEffect, useMemo, useState, type ChangeEvent } from "react";
import { Link } from "react-router-dom";
import {
  attachmentPath,
  createSharedDocument,
  getCostSteps,
  getRunActuals,
  getRuns,
  errorMessage,
  getDocument,
  getDocumentAttachments,
  getInvoiceRegister,
  isAbortError,
  resolveDocumentParts,
  updateCostLine,
  uploadDocumentAttachment,
  voidCostLine,
  type CostLineKind,
  type CostStepCatalog,
  type DocumentAttachment,
  type InvoiceRegister,
  type RunActuals,
  type RunInfo,
  type RunCostDocumentRow,
  type RunCostLineRow,
} from "../api";
import { useDialog } from "../components/Dialog";
import OrderDialog from "../components/invoices/OrderDialog";
import PlanLinkDialog from "../components/invoices/PlanLinkDialog";
import JlcImportPanel from "../components/invoices/JlcImportPanel";
import JlcSessionStrip from "../components/invoices/JlcSessionStrip";
import JlcStagedPanel from "../components/invoices/JlcStagedPanel";
import StockReconcile from "../components/invoices/StockReconcile";
import WriteLog from "../components/invoices/WriteLog";
import ProductionDashboard from "../components/invoices/ProductionDashboard";
import SplitLineDialog, { type RunOption } from "../components/invoices/SplitLineDialog";
import { ErrorBanner, Spinner } from "../components/Ui";
import { useStickyState } from "../useStickyState";
import { fileHref } from "../viewkind";

const KINDS: CostLineKind[] = [
  "part", "fab", "assembly", "tooling", "freight",
  "duty", "tax", "rework", "packaging", "service", "other",
];

function money(v: number | null | undefined, currency = "USD"): string {
  if (v == null) return "—";
  return `${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

function plain(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Depth of a line in its document's tree, for indenting the label. */
function depthOf(line: RunCostLineRow, byId: Map<number, RunCostLineRow>): number {
  let d = 0;
  let cur = line.parent_line_id;
  const seen = new Set<number>();
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    d += 1;
    cur = byId.get(cur)?.parent_line_id ?? null;
  }
  return d;
}

/** Parents before children, each family in position order. */
function treeOrder(lines: RunCostLineRow[]): RunCostLineRow[] {
  const kids = new Map<number, RunCostLineRow[]>();
  const roots: RunCostLineRow[] = [];
  for (const li of lines) {
    if (li.parent_line_id) {
      const list = kids.get(li.parent_line_id) || [];
      list.push(li);
      kids.set(li.parent_line_id, list);
    } else {
      roots.push(li);
    }
  }
  const bypos = (a: RunCostLineRow, b: RunCostLineRow) => a.position - b.position || a.id - b.id;
  const out: RunCostLineRow[] = [];
  const walk = (list: RunCostLineRow[]) => {
    for (const li of [...list].sort(bypos)) {
      out.push(li);
      walk(kids.get(li.id) || []);
    }
  };
  walk(roots);
  return out;
}

interface NewLine {
  kind: CostLineKind;
  label: string;
  qty: string;
  unit_price: string;
  mpn: string;
}

function blankLine(): NewLine {
  return { kind: "other", label: "", qty: "1", unit_price: "", mpn: "" };
}

export default function Invoices() {
  const dialog = useDialog();
  const [reg, setReg] = useState<InvoiceRegister | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useStickyState<number | null>("invoices:expanded", null);
  const [doc, setDoc] = useState<RunCostDocumentRow | null>(null);
  const [docError, setDocError] = useState<string | null>(null);
  const [splitting, setSplitting] = useState<RunCostLineRow | null>(null);
  const [linking, setLinking] = useState<RunCostLineRow | null>(null);
  const [adding, setAdding] = useState(false);
  const [pricing, setPricing] = useState<{ run: RunInfo; actuals: RunActuals | null } | null>(null);
  const [onlyProblems, setOnlyProblems] = useStickyState("invoices:problems", false);
  const [stepCatalog, setStepCatalog] = useState<CostStepCatalog | null>(null);
  // Bumped after any write that moved money, so the register figures and the
  // write log are never showing state from either side of an apply.
  const [writeSeq, setWriteSeq] = useState(0);
  useEffect(() => {
    const ac = new AbortController();
    getCostSteps(ac.signal).then(setStepCatalog).catch(() => setStepCatalog(null));
    return () => ac.abort();
  }, []);

  const setLineStep = async (line: RunCostLineRow, step: string) => {
    setBusy(true);
    try {
      await updateCostLine(line.id, { plan_key: step });
      refreshAll();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not set the step" });
    } finally {
      setBusy(false);
    }
  };

  const load = useCallback((signal?: AbortSignal) => {
    getInvoiceRegister(signal)
      .then((r) => {
        setReg(r);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  const loadDoc = useCallback((id: number, signal?: AbortSignal) => {
    getDocument(id, signal)
      .then((d) => {
        setDoc(d);
        setDocError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setDocError(errorMessage(err));
      });
  }, []);

  useEffect(() => {
    if (expanded == null) {
      setDoc(null);
      return;
    }
    const ac = new AbortController();
    loadDoc(expanded, ac.signal);
    return () => ac.abort();
  }, [expanded, loadDoc]);

  const runOptions: RunOption[] = useMemo(() => {
    if (!reg) return [];
    return Object.entries(reg.runs)
      .map(([id, r]) => ({
        id: Number(id),
        label: r.label,
        project_id: r.project_id,
        project_name: reg.projects[String(r.project_id)] || `project ${r.project_id}`,
      }))
      .sort((a, b) => a.project_name.localeCompare(b.project_name) || a.label.localeCompare(b.label));
  }, [reg]);

  const projectOptions = useMemo(
    () =>
      reg
        ? Object.entries(reg.projects)
            .map(([id, name]) => ({ id: Number(id), name }))
            .sort((a, b) => a.name.localeCompare(b.name))
        : [],
    [reg],
  );

  const refreshAll = () => {
    load();
    if (expanded != null) loadDoc(expanded);
  };

  const assignLine = async (line: RunCostLineRow, dest: string) => {
    const [kind, id] = dest ? dest.split(":") : ["", ""];
    setBusy(true);
    try {
      await updateCostLine(line.id, {
        // "excluded" is recorded-but-not-charged, so it must clear any destination
        allocate: dest === "excluded" ? "excluded" : "none",
        run_id: kind === "run" ? Number(id) : null,
        project_id: kind === "project" ? Number(id) : null,
      });
      refreshAll();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not reassign the position" });
    } finally {
      setBusy(false);
    }
  };

  const void_ = async (line: RunCostLineRow) => {
    const ok = await dialog.confirm(
      `Void “${line.label || line.kind}”?${line.is_header ? " Its shares are voided too." : ""}`,
      { title: "Void position", confirmLabel: "Void", tone: "danger" },
    );
    if (!ok) return;
    setBusy(true);
    try {
      await voidCostLine(line.id);
      refreshAll();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not void the position" });
    } finally {
      setBusy(false);
    }
  };

  /** Open the order/price editor. Needs the run itself (the register only carries a
   *  summary) and its actuals, so the margin preview is against real cost. */
  const openPricing = async (runId: number, projectId: number) => {
    setBusy(true);
    try {
      const [runs, actuals] = await Promise.all([
        getRuns(projectId),
        getRunActuals(runId).catch(() => null),
      ]);
      const run = runs.find((r) => r.id === runId);
      if (run) setPricing({ run, actuals });
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not open the order" });
    } finally {
      setBusy(false);
    }
  };

  const resolveParts = async (docId: number) => {
    setBusy(true);
    try {
      const r = await resolveDocumentParts(docId);
      await dialog.alert(
        `Matched ${r.resolved} of ${r.checked} part lines to library components.` +
          (r.unresolved.length ? `\n\nStill unmatched: ${r.unresolved.join(", ")}` : ""),
        { title: "Resolve parts" },
      );
      refreshAll();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Resolve failed" });
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="main-solo">
        <div className="page">
          <ErrorBanner message={error} />
        </div>
      </div>
    );
  }
  if (!reg) {
    return (
      <div className="main-solo">
        <div className="page">
          <Spinner label="Loading the invoice register…" />
        </div>
      </div>
    );
  }

  const s = reg.summary;
  const problem = (d: RunCostDocumentRow) =>
    !d.reconciled || (d.doc_type !== "proforma" && !d.assignment.fully_assigned);
  const docs = onlyProblems ? reg.documents.filter(problem) : reg.documents;
  const lineById = new Map((doc?.lines || []).map((li) => [li.id, li]));
  const liveLines = (doc?.lines || []).filter((li) => !li.voided);
  const docCurrency = doc?.currency || "USD";
  const runForLine = (li: RunCostLineRow) =>
    li.allocate === "excluded"
      ? "excluded"
      : li.run_id ? `run:${li.run_id}` : li.project_id ? `project:${li.project_id}` : "";
  const projectOfLine = (li: RunCostLineRow): number | null => {
    if (li.project_id) return li.project_id;
    if (li.run_id) return reg.runs[String(li.run_id)]?.project_id ?? null;
    if (doc?.project_id) return doc.project_id;
    if (doc?.run_id) return reg.runs[String(doc.run_id)]?.project_id ?? null;
    return null;
  };

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Invoices</h1>
          <span className="toolbar-total">
            {s.document_count} documents · {money(s.total_usd)} total
          </span>
          <label className="muted">
            <input
              type="checkbox"
              checked={onlyProblems}
              onChange={(e) => setOnlyProblems(e.target.checked)}
            />{" "}
            only unfinished
          </label>
          <button type="button" className="btn btn-sm" onClick={refreshAll} disabled={busy}>
            Refresh
          </button>
          <button type="button" className="btn btn-sm btn-primary" onClick={() => setAdding((v) => !v)}>
            {adding ? "Close" : "New invoice"}
          </button>
        </div>

        {/* ------------------------------------------------------- dashboard */}
        <ProductionDashboard reg={reg} />

        {/* Does the stock account close? The register's identities cannot answer
            this — they derive on-hand from purchases and draws, so they balance by
            construction whatever the real quantities are. */}
        <StockReconcile key={`sr-${writeSeq}`} />

        {/* --------------------------------------------- JLC import decisions */}
        {/* The session strip comes FIRST: a dead session is the most common reason
            a sync fails, and the fix (paste fresh cookies) is only possible here. */}
        <JlcSessionStrip />
        {/* Import comes BEFORE deciding: an order's charges cannot be pointed at a
            run until the document carrying them exists. */}
        <JlcStagedPanel
          key={`jsp-${writeSeq}`}
          onImported={() => {
            refreshAll();
            setWriteSeq((n) => n + 1);
          }}
        />
        <JlcImportPanel
          onApplied={() => {
            refreshAll();
            setWriteSeq((n) => n + 1);
          }}
        />

        {/* Every write that moved money, each one undoable. */}
        <WriteLog key={`wl-${writeSeq}`} onReversed={refreshAll} />

        {/* ---------------------------------------------------- reconciliation */}
        <div className="card pad">
          <h2 className="card-title">Where the money went</h2>
          <p className="card-subtitle">
            Every document's total lands in exactly one bucket. Converted to USD at each
            document's pinned rate, or the rate history at its date.
          </p>
          <div className="table-wrap">
            <table className="data data-fixed invoice-sum-table">
              <thead>
                <tr>
                  <th className="num">Invoiced</th>
                  <th className="num">To runs</th>
                  <th className="num">To projects</th>
                  <th className="num">To the pool</th>
                  <th className="num">Excluded</th>
                  <th className="num">Unassigned</th>
                  <th className="num">Residual</th>
                  <th className="num">Gap</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="num">{plain(s.total_usd)}</td>
                  <td className="num">{plain(s.to_runs_usd)}</td>
                  <td className="num">{plain(s.to_projects_usd)}</td>
                  <td className="num">{plain(s.to_pool_usd)}</td>
                  <td className="num muted" title="reclaimable VAT and prepaid components already in the pool">
                    {plain(s.excluded_usd)}
                  </td>
                  <td className={s.unassigned_usd ? "num" : "num muted"}>
                    {s.unassigned_usd ? (
                      <span className="pill warn">{plain(s.unassigned_usd)}</span>
                    ) : (
                      plain(s.unassigned_usd)
                    )}
                  </td>
                  <td className={s.residual_usd ? "num" : "num muted"}>
                    {s.residual_usd ? (
                      <span className="pill warn">{plain(s.residual_usd)}</span>
                    ) : (
                      plain(s.residual_usd)
                    )}
                  </td>
                  <td className="num">
                    {Math.abs(s.gap_usd ?? 0) < 0.05 ? (
                      <span className="pill ok">0</span>
                    ) : (
                      <span className="pill err">{plain(s.gap_usd)}</span>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <h2 className="card-title">Component pool</h2>
          <p className="card-subtitle">
            Parts are stockpile, so runs pay for what they drew rather than for a purchase.
            Bought ± adjustments − drawn must equal what is still on hand.
          </p>
          <div className="table-wrap">
            <table className="data data-fixed invoice-pool-table">
              <thead>
                <tr>
                  <th className="num">Purchased</th>
                  <th className="num">Adjustments</th>
                  <th className="num">Drawn by runs</th>
                  <th className="num">On hand</th>
                  <th className="num">Parts</th>
                  <th>Balance</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="num">{plain(reg.pool.purchased_usd)}</td>
                  <td className="num">{plain(reg.pool.adjustments_usd)}</td>
                  <td className="num">{plain(reg.pool.drawn_usd)}</td>
                  <td className="num">{plain(reg.pool.on_hand_usd)}</td>
                  <td className="num">{reg.pool.part_count}</td>
                  <td>
                    <span className={reg.pool.balanced ? "pill ok" : "pill err"}>
                      {reg.pool.balanced ? "balanced" : "does not balance"}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {s.unknown_rates.length ? (
            <div className="banner-warn">
              No exchange rate for {s.unknown_rates.join(", ")} — those documents are counted at face
              value, so the totals above are understated.
            </div>
          ) : null}
          {reg.issues.unreconciled.length ? (
            <div className="banner-error">
              {reg.issues.unreconciled.length} document
              {reg.issues.unreconciled.length === 1 ? "" : "s"} whose lines do not add up to the
              printed total:{" "}
              {reg.issues.unreconciled
                .map((u) => `${u.supplier} ${u.doc_number} (${plain(u.lines_total)} vs ${plain(u.total_amount)} ${u.currency})`)
                .join("; ")}
            </div>
          ) : null}
          {reg.issues.unassigned.length ? (
            <div className="banner-warn">
              {reg.issues.unassigned.length} document
              {reg.issues.unassigned.length === 1 ? "" : "s"} still carry money nobody is paying for.
              Expand them below and split or assign the positions.
            </div>
          ) : (
            <div className="banner-ok">Every position is assigned to a run, a project or the pool.</div>
          )}
        </div>

        {/* ---------------------------------------------------------- new invoice */}
        {adding ? (
          <NewInvoiceCard
            runs={runOptions}
            projects={projectOptions}
            onDone={(created) => {
              setAdding(false);
              load();
              if (created) setExpanded(created);
            }}
          />
        ) : null}

        {/* ---------------------------------------------------- run reconciliation */}
        <div className="card pad">
          <h2 className="card-title">What each run cost, and what it earned</h2>
          <p className="card-subtitle">
            Cost is direct invoice positions plus what the run drew from the component pool — the
            same arithmetic the run's own costs tab shows. Income is the price per device times the
            units billed, converted at the order date. Click a price to set it.
          </p>
          <div className="table-wrap">
            <table className="data data-fixed invoice-runs-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Project</th>
                  <th className="num">Units</th>
                  <th className="num">Cost USD</th>
                  <th className="num">Cost/dev</th>
                  <th className="num">Price/dev</th>
                  <th className="num">Revenue USD</th>
                  <th className="num">Margin USD</th>
                  <th className="num">Margin %</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(reg.by_run_usd).length === 0 ? (
                  <tr>
                    <td className="empty" colSpan={9}>
                      No run has been charged yet.
                    </td>
                  </tr>
                ) : null}
                {Object.entries(reg.by_run_usd)
                  .sort((a, b) => (reg.runs[a[0]]?.run_date || "").localeCompare(reg.runs[b[0]]?.run_date || ""))
                  .map(([rid, v]) => {
                    const run = reg.runs[rid];
                    const pid = run?.project_id;
                    return (
                      <tr key={rid}>
                        <td title={run?.label}>
                          {pid ? (
                            <Link className="comp-link" to={`/projects/${pid}`}>
                              {run?.label || `run ${rid}`}
                            </Link>
                          ) : (
                            run?.label || `run ${rid}`
                          )}
                        </td>
                        <td className="muted" title={reg.projects[String(pid)]}>
                          {reg.projects[String(pid)] || "—"}
                        </td>
                        <td className="num">{run?.qty ?? "—"}</td>
                        <td className="num" title={`direct ${plain(v.direct_usd)} + components ${plain(v.components_usd)}`}>
                          {plain(v.total_usd)}
                        </td>
                        <td className="num">
                          {run?.qty ? plain((v.total_usd ?? 0) / run.qty) : "—"}
                        </td>
                        <td className="num">
                          <button type="button" className="btn btn-sm" disabled={busy}
                                  title="Set the price per device and the customer order"
                                  onClick={() => pid && openPricing(Number(rid), pid)}>
                            {run?.sale_unit_price != null
                              ? `${run.sale_unit_price} ${run.sale_currency || ""}`.trim()
                              : "set price"}
                          </button>
                        </td>
                        <td className="num">{plain(v.revenue_usd)}</td>
                        <td className={"num" + ((v.margin_usd ?? 0) < 0 ? " err-text" : "")}>
                          {plain(v.margin_usd)}
                        </td>
                        <td className={"num" + ((v.margin_pct ?? 0) < 0 ? " err-text" : "")}
                            title={run?.customer || run?.order_ref
                              ? `${run.customer}${run.order_ref ? ` · ${run.order_ref}` : ""}`
                              : "no customer recorded"}>
                          {v.margin_pct == null ? "—" : `${v.margin_pct.toFixed(1)}%`}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ------------------------------------------------------------ documents */}
        <div className="card pad">
          <h2 className="card-title">Documents</h2>
          <div className="table-wrap">
            <table className="data data-fixed invoices-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Supplier</th>
                  <th>Number</th>
                  <th className="num">Total</th>
                  <th>Assigned to</th>
                  <th>State</th>
                  <th className="ctr">Lines</th>
                </tr>
              </thead>
              <tbody>
                {docs.length === 0 ? (
                  <tr>
                    <td className="empty" colSpan={7}>
                      {onlyProblems ? "Nothing unfinished — every document is assigned." : "No documents yet."}
                    </td>
                  </tr>
                ) : null}
                {docs.map((d) => {
                  const a = d.assignment;
                  const dest: string[] = [];
                  for (const [rid, amount] of Object.entries(a.by_run)) {
                    dest.push(`${reg.runs[rid]?.label || `run ${rid}`}: ${plain(amount)}`);
                  }
                  for (const [pid, amount] of Object.entries(a.by_project)) {
                    dest.push(`${reg.projects[pid] || `project ${pid}`}: ${plain(amount)}`);
                  }
                  if (a.pool) dest.push(`pool: ${plain(a.pool)}`);
                  const destText = dest.join(" · ") || "—";
                  const open = expanded === d.id;
                  return (
                    <Fragment key={d.id}>
                      <tr className={open ? "row-open" : undefined}>
                        <td className="mono">{d.doc_date || "—"}</td>
                        <td title={d.supplier}>{d.supplier || "—"}</td>
                        <td className="mono" title={`${d.doc_number} ${d.external_id}`}>
                          {d.doc_number || d.external_id || "—"}
                        </td>
                        <td className="num" title={`${plain(d.total_usd)} USD`}>
                          {money(d.total_amount, d.currency)}
                        </td>
                        <td className="muted" title={destText}>
                          {destText}
                        </td>
                        <td>
                          {d.doc_type === "proforma" ? (
                            <span className="pill neutral">proforma</span>
                          ) : !d.reconciled ? (
                            <span className="pill err">does not add up</span>
                          ) : a.unassigned ? (
                            <span className="pill warn">{plain(a.unassigned)} unassigned</span>
                          ) : a.residual ? (
                            <span className="pill warn">{plain(a.residual)} residual</span>
                          ) : (
                            <span className="pill ok">assigned</span>
                          )}
                        </td>
                        <td className="ctr">
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => setExpanded(open ? null : d.id)}
                          >
                            {open ? "Hide" : `${d.line_count}`}
                          </button>
                        </td>
                      </tr>
                      {open ? (
                        <tr>
                          <td className="row-expand" colSpan={7}>
                            {docError ? <ErrorBanner message={docError} /> : null}
                            {!doc || doc.id !== d.id ? (
                              <Spinner label="Loading positions…" />
                            ) : (
                              <>
                                <p className="muted">
                                  {d.notes ? d.notes : "No notes on this document."}
                                </p>
                                <div className="btn-row">
                                  <Originals docId={d.id} onChange={load} />
                                  <button
                                    type="button"
                                    className="btn btn-sm"
                                    disabled={busy}
                                    onClick={() => resolveParts(d.id)}
                                  >
                                    Resolve parts
                                  </button>
                                </div>
                                <div className="table-wrap">
                                  <table className="data data-fixed invoice-lines-table">
                                    <thead>
                                      <tr>
                                        <th>Kind</th>
                                        <th>Position</th>
                                        <th className="num">Qty</th>
                                        <th className="num">Unit</th>
                                        <th className="num">Amount</th>
                                        <th>Charge to</th>
                                        <th>Planned as</th>
                                        <th className="ctr">Split</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {treeOrder(liveLines).map((li) => {
                                        const d0 = depthOf(li, lineById);
                                        return (
                                          <tr key={li.id} className={li.is_header ? "muted" : undefined}>
                                            <td>{li.kind}</td>
                                            <td title={li.label}>
                                              <span className={`tree-indent tree-indent-${Math.min(d0, 3)}`} />
                                              {li.is_header ? "▾ " : d0 ? "· " : ""}
                                              {li.label || "—"}
                                            </td>
                                            <td className="num">{li.qty_effective ?? li.qty}</td>
                                            <td className="num">{li.unit_price}</td>
                                            <td className="num" title={li.is_header ? "split — the shares below carry this money" : undefined}>
                                              {plain(li.line_total)}
                                              {li.is_header ? (
                                                <>
                                                  {" "}
                                                  <span className="pill neutral">split</span>
                                                  {li.residual ? (
                                                    <span className="pill warn">
                                                      {plain(li.residual)} left
                                                    </span>
                                                  ) : null}
                                                </>
                                              ) : null}
                                            </td>
                                            <td>
                                              {li.is_header ? (
                                                <span className="dim">shares below</span>
                                              ) : li.kind === "part" && !li.run_id
                                                  && li.allocate !== "excluded" ? (
                                                <span className="dim" title="parts feed the shared pool; runs draw from it">
                                                  pool
                                                </span>
                                              ) : (li.allocate === "by_value" || li.allocate === "by_qty")
                                                  && !li.run_id && !li.project_id ? (
                                                <span
                                                  className="dim"
                                                  title={"landed cost — spread " +
                                                    (li.allocate === "by_value" ? "by value" : "by quantity") +
                                                    " over this document's part lines, so it raises their pool unit cost"}
                                                >
                                                  pool (spread)
                                                </span>
                                              ) : (
                                                <select
                                                  className="row-input"
                                                  value={runForLine(li)}
                                                  disabled={busy}
                                                  onChange={(e) => assignLine(li, e.target.value)}
                                                >
                                                  <option value="">— nobody —</option>
                                                  {runOptions.map((r) => (
                                                    <option key={`run:${r.id}`} value={`run:${r.id}`}>
                                                      {r.project_name} · {r.label}
                                                    </option>
                                                  ))}
                                                  {projectOptions.map((p) => (
                                                    <option key={`project:${p.id}`} value={`project:${p.id}`}>
                                                      {p.name} (no run)
                                                    </option>
                                                  ))}
                                                  <option value="excluded">
                                                    nobody, on purpose (excluded)
                                                  </option>
                                                </select>
                                              )}
                                            </td>
                                            <td title={li.plan_ref || ""}>
                                              {li.is_header ? (
                                                <span className="dim">—</span>
                                              ) : (
                                                <select
                                                  className="row-input mono"
                                                  disabled={busy}
                                                  value={li.plan_key && li.plan_key.includes(":") ? li.plan_key : ""}
                                                  title={"production step — invoice money billed under a step is matched to the planned cost item carrying the same step automatically"}
                                                  onChange={(e) => {
                                                    if (e.target.value === "__link") { setLinking(li); return; }
                                                    void setLineStep(li, e.target.value);
                                                  }}
                                                >
                                                  <option value="">— no step —</option>
                                                  {Object.entries(stepCatalog?.stages ?? {}).map(([stage, stageLabel]) => (
                                                    <optgroup key={stage} label={stageLabel}>
                                                      {(stepCatalog?.steps ?? []).filter((st) => st.stage === stage).map((st) => (
                                                        <option key={st.key} value={st.key}>{st.key}</option>
                                                      ))}
                                                    </optgroup>
                                                  ))}
                                                  <option value="__link">link to a specific plan item…</option>
                                                </select>
                                              )}
                                            </td>
                                            <td className="ctr">
                                              <button
                                                type="button"
                                                className="btn btn-sm"
                                                disabled={busy}
                                                onClick={() => setSplitting(li)}
                                              >
                                                {li.is_header ? "edit" : "split"}
                                              </button>
                                              <button
                                                type="button"
                                                className="btn btn-sm row-del"
                                                disabled={busy}
                                                title="Void this position"
                                                onClick={() => void_(li)}
                                              >
                                                ×
                                              </button>
                                            </td>
                                          </tr>
                                        );
                                      })}
                                    </tbody>
                                  </table>
                                </div>
                              </>
                            )}
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {splitting && doc ? (
        <SplitLineDialog
          line={splitting}
          parentAmount={splitting.line_total ?? 0}
          currency={splitting.currency || docCurrency}
          runs={runOptions}
          projects={projectOptions}
          existing={liveLines.filter((li) => li.parent_line_id === splitting.id)}
          onClose={(updated) => {
            setSplitting(null);
            if (updated) {
              setDoc(updated);
              load();
            }
          }}
        />
      ) : null}
      {pricing ? (
        <OrderDialog
          run={pricing.run}
          actuals={pricing.actuals}
          onClose={(changed) => {
            setPricing(null);
            if (changed) refreshAll();
          }}
        />
      ) : null}
      {linking && doc ? (
        <PlanLinkDialog
          line={linking}
          projectId={projectOfLine(linking) as number}
          projectName={reg.projects[String(projectOfLine(linking))] || ""}
          currency={linking.currency || docCurrency}
          supplier={doc.supplier}
          onClose={(changed) => {
            setLinking(null);
            if (changed) refreshAll();
          }}
        />
      ) : null}
    </div>
  );
}

// --------------------------------------------------------- supplier originals

/** The scanned/PDF original filed with a document. Kept as its own component so
 *  the expanded row does not reload every attachment list on each keystroke. */
function Originals({ docId, onChange }: { docId: number; onChange: () => void }) {
  const dialog = useDialog();
  const [files, setFiles] = useState<DocumentAttachment[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback((signal?: AbortSignal) => {
    getDocumentAttachments(docId, signal)
      .then(setFiles)
      .catch((err) => {
        if (!isAbortError(err)) setFiles([]);
      });
  }, [docId]);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  const pick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      await uploadDocumentAttachment(docId, file);
      load();
      onChange();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Upload failed" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <span className="muted">Original:</span>
      {files === null ? (
        <span className="dim">…</span>
      ) : files.length === 0 ? (
        <span className="dim">none filed</span>
      ) : (
        files.map((f) => (
          // fileHref sends a PDF to the browser's own viewer and anything the
          // /view page can render (image, CAD) to that page — never a download
          <a
            key={f.id}
            className="comp-link"
            href={fileHref(attachmentPath(f.id), f.filename)}
            target="_blank"
            rel="noreferrer"
            title={`${f.filename} · ${Math.round(f.size_bytes / 1024)} kB`}
          >
            {f.filename}
          </a>
        ))
      )}
      <label className="btn btn-sm">
        {busy ? "Uploading…" : "Attach"}
        <input type="file" hidden onChange={pick} disabled={busy} />
      </label>
    </>
  );
}

// ------------------------------------------------------------- new invoice form

function NewInvoiceCard({
  runs, projects, onDone,
}: {
  runs: RunOption[];
  projects: { id: number; name: string }[];
  onDone: (createdId: number | null) => void;
}) {
  const [supplier, setSupplier] = useState("");
  const [docNumber, setDocNumber] = useState("");
  const [externalId, setExternalId] = useState("");
  const [docDate, setDocDate] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [total, setTotal] = useState("");
  const [docType, setDocType] = useState("invoice");
  const [dest, setDest] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<NewLine[]>([blankLine()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sum = lines.reduce((s, l) => s + Number(l.qty || 0) * Number(l.unit_price || 0), 0);
  const totalNum = total.trim() === "" ? null : Number(total);
  const mismatch = totalNum != null && Math.abs(sum - totalNum) > 0.05;

  const patch = (i: number, next: Partial<NewLine>) =>
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...next } : l)));

  const save = async () => {
    if (!supplier.trim()) {
      setError("A supplier is required — it is how the document is recognised later.");
      return;
    }
    const [kind, id] = dest ? dest.split(":") : ["", ""];
    setBusy(true);
    setError(null);
    try {
      // Always created as a SHARED document (no project): an invoice that covers
      // several products has no single owner, and positions carry the split.
      // A whole-document destination is applied per line instead.
      const created = await createSharedDocument({
        doc_type: docType,
        supplier: supplier.trim(),
        doc_number: docNumber.trim(),
        external_id: externalId.trim(),
        doc_date: docDate.trim(),
        currency: currency.trim() || "USD",
        total_amount: totalNum,
        notes: notes.trim(),
        lines: lines
          .filter((l) => l.label.trim() !== "" || Number(l.unit_price || 0) !== 0)
          .map((l) => ({
            kind: l.kind,
            basis: "per_run" as const,
            label: l.label.trim(),
            mpn: l.mpn.trim(),
            qty: Number(l.qty || 0),
            unit_price: Number(l.unit_price || 0),
            run_id: kind === "run" ? Number(id) : null,
            project_id: kind === "project" ? Number(id) : null,
          })),
      });
      onDone(created.id);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="card pad edit-card">
      <h2 className="card-title">New invoice</h2>
      <p className="card-subtitle">
        Enter it as the supplier printed it. Positions are handed out to runs afterwards — one
        invoice can pay for several batches, and a position can be split.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      <div className="edit-grid">
        <label>
          Supplier
          <input className="text" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
        </label>
        <label>
          Document number
          <input className="text" value={docNumber} onChange={(e) => setDocNumber(e.target.value)} />
        </label>
        <label>
          Supplier order id
          <input
            className="text"
            value={externalId}
            placeholder="JLC Batch No, POB0…"
            onChange={(e) => setExternalId(e.target.value)}
          />
        </label>
        <label>
          Date
          <input
            className="text"
            value={docDate}
            placeholder="2025-04-13"
            onChange={(e) => setDocDate(e.target.value)}
          />
        </label>
        <label>
          Currency
          <input className="text" value={currency} onChange={(e) => setCurrency(e.target.value)} />
        </label>
        <label>
          Printed total
          <input className="text num" value={total} onChange={(e) => setTotal(e.target.value)} />
        </label>
        <label>
          Type
          <select className="text" value={docType} onChange={(e) => setDocType(e.target.value)}>
            <option value="invoice">invoice</option>
            <option value="proforma">proforma (not money)</option>
            <option value="receipt">receipt</option>
            <option value="credit_note">credit note</option>
          </select>
        </label>
        <label>
          Charge every position to
          <select className="text" value={dest} onChange={(e) => setDest(e.target.value)}>
            <option value="">— decide per position —</option>
            {runs.map((r) => (
              <option key={`run:${r.id}`} value={`run:${r.id}`}>
                {r.project_name} · {r.label}
              </option>
            ))}
            {projects.map((p) => (
              <option key={`project:${p.id}`} value={`project:${p.id}`}>
                {p.name} (no run)
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Notes
        <textarea
          className="note-textarea"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What this document covers, and any split arithmetic"
        />
      </label>

      <div className="table-wrap">
        <table className="data data-fixed invoice-new-lines-table">
          <thead>
            <tr>
              <th>Kind</th>
              <th>Position</th>
              <th>MPN</th>
              <th className="num">Qty</th>
              <th className="num">Unit price</th>
              <th className="num">Amount</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td>
                  <select
                    className="row-input"
                    value={l.kind}
                    onChange={(e) => patch(i, { kind: e.target.value as CostLineKind })}
                  >
                    {KINDS.map((k) => (
                      <option key={k} value={k}>{k}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input className="row-input" value={l.label} onChange={(e) => patch(i, { label: e.target.value })} />
                </td>
                <td>
                  <input
                    className="row-input mono"
                    value={l.mpn}
                    placeholder={l.kind === "part" ? "required for parts" : ""}
                    onChange={(e) => patch(i, { mpn: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    className="row-input num"
                    inputMode="decimal"
                    value={l.qty}
                    onChange={(e) => patch(i, { qty: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    className="row-input num"
                    inputMode="decimal"
                    value={l.unit_price}
                    onChange={(e) => patch(i, { unit_price: e.target.value })}
                  />
                </td>
                <td className="num">
                  {plain(Number(l.qty || 0) * Number(l.unit_price || 0))}
                </td>
                <td className="ctr">
                  <button
                    type="button"
                    className="btn btn-sm row-del"
                    onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={() => setLines((ls) => [...ls, blankLine()])}>
          Add position
        </button>
        <span className={mismatch ? "pill err" : "muted"}>
          positions {plain(sum)} {currency}
          {totalNum != null ? ` · printed ${plain(totalNum)}` : ""}
          {mismatch ? " — does not add up" : ""}
        </span>
      </div>

      <div className="btn-row">
        <button type="button" className="btn" onClick={() => onDone(null)} disabled={busy}>
          Cancel
        </button>
        <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save invoice"}
        </button>
      </div>
    </div>
  );
}
