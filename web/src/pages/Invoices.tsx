/** Invoices — where supplier documents are entered and their positions handed
 *  out to batches and projects.
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
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import {
  attachmentPath,
  createCorrection,
  createSharedDocument,
  getCostSteps,
  resolveAllParts,
  editDocumentLines,
  errorMessage,
  getDocument,
  getDocumentAttachments,
  getInvoiceRegister,
  isAbortError,
  resolveDocumentParts,
  uploadDocumentAttachment,
  type CostStepCatalog,
  type DocumentAttachment,
  type InvoiceRegister,
  type RunCostDocumentRow,
  type RunCostLineRow,
} from "../api";
import { CheckField } from "../components/Field";
import { useDialog } from "../components/Dialog";
import InvoiceFields, { type InvoiceHeader } from "../components/invoices/InvoiceFields";
import InvoiceLinesTable, { blankDraft, draftToLineIn, toDraft, type LineDraft }
  from "../components/invoices/InvoiceLinesTable";
import PlanLinkDialog from "../components/invoices/PlanLinkDialog";
import SplitLineDialog from "../components/invoices/SplitLineDialog";
import DataTable, { type Column } from "../components/DataTable";
import { ErrorBanner, Spinner } from "../components/Ui";
import { useStickyState } from "../useStickyState";
import { fileHref } from "../viewkind";

import { amount as money, plain } from "../format";
import {
  type RunOption,
} from "../components/costs";

/** The document's header fields as the shared form holds them. */
function headerOf(d: RunCostDocumentRow): InvoiceHeader {
  return {
    supplier: d.supplier || "",
    doc_number: d.doc_number || "",
    external_id: d.external_id || "",
    doc_date: d.doc_date || "",
    currency: d.currency || "USD",
    total: d.total_amount == null ? "" : String(d.total_amount),
    doc_type: d.doc_type || "invoice",
    notes: d.notes || "",
    dest: "",
  };
}

/** What the DOCUMENT itself charges to, worded for the "from this document (…)"
 *  option. Empty when it names neither, which is the ordinary shared invoice.
 *  A line that stores no destination falls back to this on the server
 *  (`run_actuals.line_destination`), so the row has to be able to say so. */
function docDefaultOf(d: RunCostDocumentRow | null, reg: InvoiceRegister | null): string {
  if (!d || !reg) return "";
  if (d.run_id) return reg.runs[String(d.run_id)]?.label || `batch ${d.run_id}`;
  if (d.project_id) return reg.projects[String(d.project_id)] || `project ${d.project_id}`;
  return "";
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


export default function Invoices() {
  const dialog = useDialog();
  const [reg, setReg] = useState<InvoiceRegister | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useStickyState<number | null>("invoices:expanded", null);
  const [doc, setDoc] = useState<RunCostDocumentRow | null>(null);
  const [docError, setDocError] = useState<string | null>(null);
  const [splitting, setSplitting] = useState<RunCostLineRow | null>(null);
  // The open document's lines as editable drafts. Rebuilt whenever the document
  // is (re)loaded; the table stages edits on this copy and writes them as one
  // batch, so an abandoned edit costs nothing.
  const [savedRows, setSavedRows] = useState<LineDraft[]>([]);
  // ONE switch for the whole document: its header fields and every position
  // become editable together, and one Save writes them in one transaction
  // (user decision 2026-09-19). A per-row switch could not express a swap
  // between two positions, and a per-field save could not either.
  const [editingDoc, setEditingDoc] = useState(false);
  const [deletedLines, setDeletedLines] = useState<Set<number>>(new Set());
  const [header, setHeader] = useState<InvoiceHeader | null>(null);
  const [savingDoc, setSavingDoc] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [linking, setLinking] = useState<RunCostLineRow | null>(null);
  const [adding, setAdding] = useState(false);
  const [onlyProblems, setOnlyProblems] = useStickyState("invoices:problems", false);
  const [stepCatalog, setStepCatalog] = useState<CostStepCatalog | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    getCostSteps(ac.signal).then(setStepCatalog).catch(() => setStepCatalog(null));
    return () => ac.abort();
  }, []);


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



  /** The global pass — every unresolved part line in every document. */
  const resolveEverywhere = async () => {
    setBusy(true);
    try {
      const r = await resolveAllParts();
      await dialog.alert(
        `Matched ${r.resolved} of ${r.checked} unresolved part line(s).` +
          (r.unresolved.length
            ? ` Still unmatched: ${r.unresolved.slice(0, 10).join(", ")}`
            : ""),
        { title: "Resolve parts everywhere" },
      );
      refreshAll();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Resolve failed" });
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
  // Rebuild the editable copy of the open document's lines whenever a different
  // document is opened or the open one is refetched. Keyed on the document id
  // plus its line identities, so an ordinary re-render does not throw away edits
  // in progress. It sits with the other hooks and ABOVE the loading returns:
  // placing it after them changed the hook order between renders and blanked the
  // page (2026-09-19).
  const rowsKey = `${doc?.id ?? 0}:${(doc?.lines || []).filter((li) => !li.voided)
    .map((li) => li.id).join(",")}`;
  const rowsKeyRef = useRef("");
  useEffect(() => {
    if (rowsKeyRef.current === rowsKey) return;
    rowsKeyRef.current = rowsKey;
    const live = (doc?.lines || []).filter((li) => !li.voided);
    const byId = new Map((doc?.lines || []).map((li) => [li.id, li]));
    setSavedRows(treeOrder(live).map((li) =>
      toDraft(li, depthOf(li, byId), !!(doc?.run_id || doc?.project_id))));
    setHeader(doc ? headerOf(doc) : null);
    setEditingDoc(false);
    setDeletedLines(new Set());
    setSaveError(null);
  }, [rowsKey]);

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

  /** The project a line's money belongs to: its own, its run's, or the
   *  document's. PlanLinkDialog needs it to load that project's cost list. */
  /** Put the open document back the way the server has it. One act, because a
   *  batch that is abandoned is abandoned whole. */
  const cancelDocEdit = () => {
    if (!doc) return;
    const live = (doc.lines || []).filter((li) => !li.voided);
    const byId = new Map((doc.lines || []).map((li) => [li.id, li]));
    setSavedRows(treeOrder(live).map((li) =>
      toDraft(li, depthOf(li, byId), !!(doc.run_id || doc.project_id))));
    setHeader(headerOf(doc));
    setDeletedLines(new Set());
    setSaveError(null);
  };

  /** Header + positions in ONE call, so the document can never be half-written
   *  and a swap between two positions nets out before the stock guard runs. */
  const saveDocEdit = async () => {
    if (!doc || !header) return;
    setSavingDoc(true);
    setSaveError(null);
    try {
      const total = header.total.trim();
      await editDocumentLines(doc.id, {
        document: {
          supplier: header.supplier.trim(),
          doc_number: header.doc_number.trim(),
          external_id: header.external_id.trim(),
          doc_date: header.doc_date.trim(),
          currency: header.currency.trim() || "USD",
          total_amount: total === "" ? null : Number(total),
          doc_type: header.doc_type,
          notes: header.notes,
        },
        updates: savedRows
          .filter((r) => r.id != null && !deletedLines.has(r.id))
          .map((r) => ({ id: r.id as number, ...draftToLineIn(r) })),
        creates: savedRows.filter((r) => r.id == null).map(draftToLineIn),
        deletes: [...deletedLines],
      });
      setEditingDoc(false);
      setDeletedLines(new Set());
      await refreshAll();
    } catch (err) {
      setSaveError(errorMessage(err));
    } finally {
      setSavingDoc(false);
    }
  };

  /** Write a CORRECTION of the open document and open it (decision 0044).
   *
   *  What a closed batch cost cannot be edited in place — the figure has already
   *  been carried onto orders — so the change is made as its own dated document
   *  that says what moved. The original keeps its printed figures.
   */
  const makeCorrection = async (d: RunCostDocumentRow) => {
    const batches = (d.locked || []).map((l) => l.label).join(", ");
    const ok = await dialog.confirm(
      `This writes a new document dated today that corrects ${d.supplier} ` +
        `${d.doc_number || `#${d.id}`}. The original is left exactly as it is.\n\n` +
        `Put on it only what CHANGED: a credit is a negative amount. It converts at ` +
        `the rate the original was pinned at, so a correction in ${d.currency} nets ` +
        `against it exactly.` +
        (batches ? `\n\nIt will be charged to ${batches}, whose books are closed.` : ""),
      { title: "Create a correction", confirmLabel: "Create it" },
    );
    if (!ok) return;
    setBusy(true);
    try {
      const made = await createCorrection(d.id, {});
      await load();
      // Open it, but do not force the edit switch on: the effect that rebuilds
      // the rows for a newly opened document resets it, so setting it here would
      // flip on and straight back off.
      setExpanded(made.id);
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Correction failed" });
    } finally {
      setBusy(false);
    }
  };

  const projectOfLine = (li: RunCostLineRow): number | null => {
    if (li.project_id) return li.project_id;
    if (li.run_id) return reg.runs[String(li.run_id)]?.project_id ?? null;
    if (doc?.project_id) return doc.project_id;
    if (doc?.run_id) return reg.runs[String(doc.run_id)]?.project_id ?? null;
    return null;
  };

  /** WHERE this document's money went, as one line of text. It is the column's
   *  sort and filter value as well as what it prints, so a filter matches what
   *  the eye can see. */
  const destTextOf = (d: RunCostDocumentRow): string => {
    const a = d.assignment;
    const dest: string[] = [];
    for (const [rid, amount] of Object.entries(a.by_run)) {
      dest.push(`${reg.runs[rid]?.label || `run ${rid}`}: ${plain(amount)}`);
    }
    for (const [pid, amount] of Object.entries(a.by_project)) {
      dest.push(`${reg.projects[pid] || `project ${pid}`}: ${plain(amount)}`);
    }
    if (a.pool) dest.push(`pool: ${plain(a.pool)}`);
    if (a.excluded) dest.push(`excluded: ${plain(a.excluded)}`);
    return dest.join(" · ") || "—";
  };

  /** Money charged to NOBODY on purpose is not money that found a home. It read
   *  `assigned` in green with an empty destination, which is how three whole JLC
   *  board invoices sat unnoticed from 2023 until somebody went looking
   *  (2026-09-18). */
  const whollyExcluded = (d: RunCostDocumentRow): boolean => {
    const a = d.assignment;
    if (!(a.excluded ?? 0)) return false;
    const dest: string[] = [];
    for (const [rid, amount] of Object.entries(a.by_run)) {
      dest.push(`${reg.runs[rid]?.label || `run ${rid}`}: ${plain(amount)}`);
    }
    for (const [pid] of Object.entries(a.by_project)) dest.push(`project ${pid}`);
    if (a.pool) dest.push("pool");
    return dest.length === 0;
  };

  /** ONE word for the state, and it is what the column sorts and filters on.
   *  The cell draws a pill from the same answer, so typing "unassigned" in the
   *  filter box finds exactly the rows showing that pill. */
  const stateOf = (d: RunCostDocumentRow): string => {
    if (d.doc_type === "proforma") return "proforma";
    if (!d.reconciled) return "does not add up";
    if (d.assignment.unassigned) return "unassigned";
    if (d.assignment.residual) return "residual";
    if (whollyExcluded(d)) return "excluded";
    return "assigned";
  };

  const docCols: Column<RunCostDocumentRow>[] = [
    { key: "date", label: "Date", width: 9, className: "mono", get: (d) => d.doc_date || "—" },
    { key: "supplier", label: "Supplier", width: 21, get: (d) => d.supplier || "—" },
    {
      key: "number",
      label: "Number",
      width: 20,
      className: "mono",
      get: (d) => `${d.doc_number} ${d.external_id}`.trim(),
      title: (d) => `${d.doc_number} ${d.external_id}`.trim(),
      render: (d) => <>{d.doc_number || d.external_id || "—"}</>,
    },
    {
      key: "total",
      label: "Total",
      width: 12,
      numeric: true,
      // Sorts on USD and PRINTS the printed currency: sorting 1,651 EUR beside
      // 1,651 USD by the number on the page would order them as equal.
      get: (d) => d.total_usd ?? 0,
      title: (d) => `${plain(d.total_usd)} USD`,
      render: (d) => <>{money(d.total_amount, d.currency)}</>,
    },
    {
      key: "dest",
      label: "Assigned to",
      width: 14,
      className: "muted",
      get: destTextOf,
      title: destTextOf,
    },
    {
      key: "state",
      label: "State",
      width: 16,
      get: stateOf,
      render: (d) => {
        const state = stateOf(d);
        return (
          <>
            {/* GLYPHS, not pills. The column already carries the money state; a
                second worded chip is ellipsised into "…", which is exactly how
                the substitution pill was lost (2026-09-19). A pill cannot be
                truncated and stay readable — a glyph cannot be truncated at
                all. */}
            {(d.locked || []).length ? (
              <span
                title={`The books are closed on ${(d.locked || []).map((l) => l.label).join(", ")}. `
                  + "This document is read-only — correct it with a new document, "
                  + "or reopen the batch."}
              >
                🔒{" "}
              </span>
            ) : null}
            {d.doc_type === "correction" ? (
              <span title="A correction of an earlier document">↩{" "}</span>
            ) : null}
            {state === "proforma" ? (
              <span className="pill neutral">proforma</span>
            ) : state === "does not add up" ? (
              <span className="pill err">does not add up</span>
            ) : state === "unassigned" ? (
              <span className="pill warn">{plain(d.assignment.unassigned)} unassigned</span>
            ) : state === "residual" ? (
              <span className="pill warn">{plain(d.assignment.residual)} residual</span>
            ) : state === "excluded" ? (
              <span className="pill neutral" title="Charged to nobody on purpose — reclaimable tax, or a board nothing in the platform carries">
                excluded
              </span>
            ) : (
              <span className="pill ok">assigned</span>
            )}
          </>
        );
      },
    },
    {
      key: "lines",
      label: "Lines",
      width: 8,
      numeric: true,
      get: (d) => d.line_count,
      title: () => "positions on this document — click the row to open them",
    },
  ];

  /** The open document's positions, under its row. `DataTable` only calls this
   *  for the row that is open, which is what keeps one document request from
   *  firing for every row on the page. */
  const renderPositions = (d: RunCostDocumentRow) => (
    <>
            {docError ? <ErrorBanner message={docError} /> : null}
            {!doc || doc.id !== d.id ? (
              <Spinner label="Loading positions…" />
            ) : (
              <>
                {saveError ? <ErrorBanner message={saveError} /> : null}
                {editingDoc && header ? (
                  <InvoiceFields
                    value={header}
                    onChange={setHeader}
                    runs={runOptions}
                    projects={projectOptions}
                    disabled={savingDoc}
                  />
                ) : (
                  <p className="muted">
                    {d.notes ? d.notes : "No notes on this document."}
                  </p>
                )}
                <CorrectionLinks doc={doc} onOpen={setExpanded} />
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
                  {(doc.locked || []).length ? (
                    <>
                      {/* A disabled checkbox with nothing beside it reads as a
                          bug. The reason and the way forward sit next to it,
                          because a refusal the user cannot act on is a dead end. */}
                      <CheckField checked={false} disabled onChange={() => {}}>
                        Edit this invoice
                      </CheckField>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={busy}
                        onClick={() => makeCorrection(doc)}
                      >
                        Create correction
                      </button>
                      <span className="muted">
                        The books are closed on{" "}
                        {(doc.locked || []).map((l) => l.label).join(", ")}, so this
                        document is settled — its cost has already gone out on
                        orders. Record what changed as a correction dated today, or
                        reopen the batch on its own page.
                      </span>
                    </>
                  ) : (
                    <CheckField
                      checked={editingDoc}
                      disabled={busy || savingDoc}
                      onChange={(on) => {
                        setEditingDoc(on);
                        if (!on) cancelDocEdit();
                      }}
                    >
                      Edit this invoice
                    </CheckField>
                  )}
                </div>
                <InvoiceLinesTable
                  mode="saved"
                  rows={savedRows}
                  setRows={setSavedRows}
                  savedById={lineById}
                  editing={editingDoc}
                  deleted={deletedLines}
                  setDeleted={setDeletedLines}
                  runs={runOptions}
                  projects={projectOptions}
                  stepCatalog={stepCatalog}
                  currency={docCurrency}
                  busy={busy}
                  docDefault={docDefaultOf(doc, reg)}
                  locked={(doc.locked || []).length > 0}
                  onSplit={(li) => setSplitting(li)}
                  onSaved={refreshAll}
                />
                {editingDoc ? (
                  <div className="btn-row">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={savingDoc || busy}
                      onClick={saveDocEdit}
                      title="The header and every position are written in ONE transaction, so a swap between two positions is legal"
                    >
                      {savingDoc ? "Saving…" : "Save changes"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={savingDoc}
                      onClick={() => { setEditingDoc(false); cancelDocEdit(); }}
                    >
                      Cancel
                    </button>
                    <span className="muted">
                      Nothing is written until you save.
                      {deletedLines.size
                        ? ` ${deletedLines.size} position${deletedLines.size === 1 ? "" : "s"} staged for voiding.`
                        : ""}
                    </span>
                  </div>
                ) : null}
              </>
            )}
    </>
  );

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
          <button
            type="button"
            className="btn btn-sm"
            disabled={busy}
            title="Match every unresolved part line across ALL documents to library components — run it after a library import."
            onClick={resolveEverywhere}
          >
            Resolve parts everywhere
          </button>
          <button type="button" className="btn btn-sm btn-primary" onClick={() => setAdding((v) => !v)}>
            {adding ? "Close" : "New invoice"}
          </button>
        </div>

        {/* ---------------------------------------------------------- new invoice */}
        {adding ? (
          <NewInvoiceCard
            runs={runOptions}
            projects={projectOptions}
          stepCatalog={stepCatalog}
            onDone={(created) => {
              setAdding(false);
              load();
              if (created) setExpanded(created);
            }}
          />
        ) : null}

        {/* ------------------------------------------------------------ documents */}
        <div className="card pad">
          <h2 className="card-title">Documents</h2>
          <div className="table-wrap">
            <DataTable
              columns={docCols}
              rows={docs}
              rowKey={(d) => d.id}
              persistKey="invoices"
              defaultSort={{ key: "date", dir: "desc" }}
              openKey={expanded}
              onOpenChange={(k) => setExpanded(k == null ? null : Number(k))}
              expand={renderPositions}
              empty={onlyProblems
                ? "Nothing unfinished — every document is assigned."
                : "No documents yet."}
            />
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

/** The correction chain around a document (decision 0044).
 *
 *  A document that has been corrected must say so, and from the correction you
 *  must be able to reach what it corrects. Without both links the correction is
 *  a second document from the same supplier with a similar number, which is
 *  exactly the confusion it exists to prevent.
 */
function CorrectionLinks({ doc, onOpen }: {
  doc: RunCostDocumentRow;
  onOpen: (id: number) => void;
}) {
  const corrects = doc.corrects_document_id;
  const by = doc.corrected_by || [];
  if (!corrects && !by.length) return null;
  return (
    <p className="muted">
      {corrects ? (
        <>
          {/* The generated note above already says WHAT is corrected and that
              the original is untouched. This line exists to be CLICKABLE, so it
              stays short rather than repeating it. */}
          Open{" "}
          <button type="button" className="linklike" onClick={() => onOpen(corrects)}>
            document {corrects}
          </button>
          .{" "}
        </>
      ) : null}
      {by.length ? (
        <>
          Corrected by{" "}
          {by.map((c, i) => (
            <Fragment key={c.id}>
              {i ? ", " : ""}
              <button type="button" className="linklike" onClick={() => onOpen(c.id)}>
                {c.doc_number || `document ${c.id}`}
              </button>
              {c.doc_date ? ` (${c.doc_date})` : ""}
            </Fragment>
          ))}
          .
        </>
      ) : null}
    </p>
  );
}

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
  runs, projects, stepCatalog, onDone,
}: {
  runs: RunOption[];
  projects: { id: number; name: string }[];
  stepCatalog: CostStepCatalog | null;
  onDone: (createdId: number | null) => void;
}) {
  const [head, setHead] = useState<InvoiceHeader>({
    supplier: "", doc_number: "", external_id: "", doc_date: "",
    currency: "USD", total: "", doc_type: "invoice", notes: "", dest: "",
  });
  const [lines, setLines] = useState<LineDraft[]>([blankDraft()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sum = lines.reduce((s, l) => s + Number(l.qty || 0) * Number(l.unit_price || 0), 0);
  const currency = head.currency;
  const totalNum = head.total.trim() === "" ? null : Number(head.total);
  const mismatch = totalNum != null && Math.abs(sum - totalNum) > 0.05;


  const save = async () => {
    if (!head.supplier.trim()) {
      setError("A supplier is required — it is how the document is recognised later.");
      return;
    }
    const [kind, id] = head.dest ? head.dest.split(":") : ["", ""];
    setBusy(true);
    setError(null);
    try {
      // Always created as a SHARED document (no project): an invoice that covers
      // several products has no single owner, and positions carry the split.
      // A whole-document destination is applied per line instead.
      const created = await createSharedDocument({
        doc_type: head.doc_type,
        supplier: head.supplier.trim(),
        doc_number: head.doc_number.trim(),
        external_id: head.external_id.trim(),
        doc_date: head.doc_date.trim(),
        currency: head.currency.trim() || "USD",
        total_amount: totalNum,
        notes: head.notes.trim(),
        // A position with no destination of its own falls back to the
        // document-wide one, which is what the "charge every position to"
        // select is for. The per-line control wins when it was used.
        lines: lines
          .filter((l) => l.label.trim() !== "" || Number(l.unit_price || 0) !== 0)
          .map((l) => {
            const line = draftToLineIn(l);
            if (!l.dest && head.dest) {
              line.run_id = kind === "run" ? Number(id) : null;
              line.project_id = kind === "project" ? Number(id) : null;
            }
            return line;
          }),
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
        Enter it as the supplier printed it. Positions are handed out to batches afterwards — one
        invoice can pay for several batches, and a position can be split.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      <InvoiceFields
        value={head}
        onChange={setHead}
        runs={runs}
        projects={projects}
        withDest
        disabled={busy}
      />

      <InvoiceLinesTable
        mode="draft"
        rows={lines}
        setRows={setLines}
        runs={runs}
        projects={projects}
        stepCatalog={stepCatalog}
        currency={currency}
      />

      <div className="btn-row">
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
