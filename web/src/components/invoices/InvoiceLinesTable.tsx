/** ONE line table, for entering an invoice and for editing a saved one.
 *
 *  There used to be two: the New invoice card's own draft table and the
 *  document view's read-only tree. They drifted — the creator never offered a
 *  component link or an exact planned cost, so a position typed by hand could
 *  only be finished by opening the document again afterwards.
 *
 *  Two modes, one markup:
 *
 *  - `draft`  — every row is editable, the parent owns the rows and saves them
 *               with the document. There is nothing to PATCH yet.
 *  - `saved`  — rows are read-only until their own checkbox is ticked, and the
 *               whole set is written by ONE atomic call.
 *
 *  **One checkbox opens the whole document, and the save is one transaction**
 *  (user decision 2026-09-19). Swapping the component mapping of two positions
 *  is a legal edit, but neither half is legal alone: each strands the draws
 *  priced against it. A per-field save cannot express it, so every change — the
 *  header included — is staged locally and written by one `editDocumentLines`
 *  call, which the backend guards on the batch's NET effect (decision 0040).
 */
import { useEffect, useRef, useState } from "react";
import {
  errorMessage,
  getSupplierBreakdown,
  resolveDocumentParts,
  splitCostLine,
  type CostLineKind,
  type CostStepCatalog,
  type RunCostLineRow,
} from "../../api";
import { plain } from "../../format";
import { ChargeToSelect, StepSelect, type RunOption } from "../costs";
import ComponentPickDialog from "../ComponentPickDialog";
import { ErrorBanner } from "../Ui";

export const KINDS: CostLineKind[] = [
  "part", "fab", "assembly", "tooling", "freight", "duty", "tax",
  "rework", "packaging", "service", "other",
];

/** A row while it is being typed into. Amounts stay STRINGS so a half-typed
 *  "1." is not rounded away under the cursor. */
export interface LineDraft {
  key: string;
  id: number | null;          // null => a row that does not exist server-side yet
  kind: CostLineKind;
  label: string;
  mpn: string;
  qty: string;
  unit_price: string;
  component_id: number | null;
  component_name: string;
  plan_key: string;
  plan_kind: string;
  plan_ref: string;
  dest: string;               // "run:5" | "project:2" | "excluded" | ""
  /** tree depth, computed by the caller from parent_line_id */
  depth: number;
}

let seq = 0;
export function blankDraft(): LineDraft {
  seq += 1;
  return {
    key: `new-${seq}`, id: null, kind: "other", label: "", mpn: "",
    qty: "1", unit_price: "", component_id: null, component_name: "",
    plan_key: "", plan_kind: "", plan_ref: "", dest: "", depth: 0,
  };
}

export function toDraft(li: RunCostLineRow, depth = 0): LineDraft {
  return {
    key: `line-${li.id}`,
    id: li.id,
    kind: li.kind,
    label: li.label,
    mpn: li.mpn || "",
    qty: String(li.qty ?? ""),
    unit_price: String(li.unit_price ?? ""),
    component_id: li.component_id,
    component_name: li.component_name || "",
    plan_key: li.plan_key || "",
    plan_kind: li.plan_kind || "",
    plan_ref: li.plan_ref || "",
    dest: li.run_id ? `run:${li.run_id}`
      : li.project_id ? `project:${li.project_id}`
      : li.allocate === "excluded" ? "excluded" : "",
    depth,
  };
}

/** The line as a fake `RunCostLineRow`, so the component dialog can be reused
 *  by a draft row that has no server id yet. */
function asRow(d: LineDraft): RunCostLineRow {
  return {
    id: d.id ?? -1, document_id: -1, run_id: null, position: 0, kind: d.kind,
    basis: "per_run", label: d.label, qty: Number(d.qty || 0),
    unit_price: Number(d.unit_price || 0), line_total: null, currency: "",
    allocate: "none", component_id: d.component_id, component_name: d.component_name,
    mpn: d.mpn, lcsc: "", description: "", plan_key: d.plan_key, plan_kind: d.plan_kind,
    notes: "",
  } as RunCostLineRow;
}

function destPatch(dest: string) {
  const [kind, id] = dest ? dest.split(":") : ["", ""];
  return {
    run_id: kind === "run" ? Number(id) : null,
    project_id: kind === "project" ? Number(id) : null,
    ...(dest === "excluded" ? { allocate: "excluded" } : {}),
  };
}

export function draftToLineIn(d: LineDraft) {
  return {
    kind: d.kind,
    basis: "per_run" as const,
    label: d.label.trim(),
    mpn: d.mpn.trim(),
    qty: Number(d.qty || 0),
    unit_price: Number(d.unit_price || 0),
    component_id: d.component_id,
    plan_key: d.plan_key,
    plan_kind: d.plan_kind,
    plan_ref: d.plan_ref,
    ...destPatch(d.dest),
  };
}

export default function InvoiceLinesTable({
  mode, rows, setRows, runs, projects, stepCatalog, currency,
  editing, deleted, setDeleted, savedById, onSplit, onSaved, busy,
}: {
  mode: "draft" | "saved";
  rows: LineDraft[];
  setRows: (next: LineDraft[]) => void;
  runs: RunOption[];
  projects: { id: number; name: string }[];
  stepCatalog: CostStepCatalog | null;
  currency: string;
  /** saved mode: the whole document is open for editing */
  editing?: boolean;
  /** saved mode: ids staged for voiding, owned by the parent so Cancel is one act */
  deleted?: Set<number>;
  setDeleted?: (next: Set<number>) => void;
  /** saved mode: the rows as the server has them, for headers, splits and totals */
  savedById?: Map<number, RunCostLineRow>;
  onSplit?: (li: RunCostLineRow) => void;
  onSaved?: () => void;
  busy?: boolean;
}) {
  const draftMode = mode === "draft";
  const open = draftMode || !!editing;
  const gone = (d: LineDraft) => d.id != null && !!deleted?.has(d.id);
  const [picking, setPicking] = useState<LineDraft | null>(null);
  const [loading, setLoading] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // EVERY header folds — a split position is a breakdown, and a breakdown is
  // worth opening when you need it and worth being out of the way otherwise.
  // A PARTS header starts folded because it is the long one (twenty-odd rows of
  // reference data); a fee breakdown is short enough to read, so it starts open
  // and keeps the shape people are used to.
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const headerIds = rows
    .filter((d) => d.id != null && savedById?.get(d.id)?.is_header)
    .map((d) => d.id as number)
    .join(",");
  const seeded = useRef("");
  useEffect(() => {
    if (seeded.current === headerIds) return;
    seeded.current = headerIds;
    setCollapsed(new Set(headerIds.split(",").filter(Boolean).map(Number)
      .filter((id) => savedById?.get(id)?.kind === "part")));
  }, [headerIds]);

  const childCount = (id: number) => savedById
    ? [...savedById.values()].filter((x) => x.parent_line_id === id && !x.voided).length
    : 0;
  const partsHeader = (id: number | null) => {
    if (id == null) return false;
    const li = savedById?.get(id);
    return !!li?.is_header && li.kind === "part";
  };
  const hidden = (d: LineDraft) => {
    let cur = d.id != null ? savedById?.get(d.id)?.parent_line_id ?? null : null;
    const seen = new Set<number>();
    while (cur != null && !seen.has(cur)) {
      seen.add(cur);
      if (collapsed.has(cur)) return true;
      cur = savedById?.get(cur)?.parent_line_id ?? null;
    }
    return false;
  };
  const toggle = (id: number) => {
    const n = new Set(collapsed);
    if (n.has(id)) n.delete(id); else n.add(id);
    setCollapsed(n);
  };

  /** Fill a supplier-parts position from the supplier's own BOM.
   *
   *  No dialog: the rows land in the table the operator is already looking at,
   *  and the document's own edit mode makes them editable in place. It still
   *  goes through `split`, which carries the stock guard and the
   *  children-may-not-exceed-the-parent rule.
   */
  const loadSupplier = async (li: RunCostLineRow) => {
    setLoading(li.id);
    setLoadError(null);
    try {
      const plan = await getSupplierBreakdown(li.id);
      if (!plan.ok) { setLoadError(plan.reason || "no supplier breakdown"); return; }
      await splitCostLine(li.id, plan.children
        .filter((c) => c.qty_supplied > 0)
        .map((c) => ({
          label: `${c.mpn || c.lcsc} - ${c.designator}`.slice(0, 200),
          kind: "part" as const,
          // A component share is a QUANTITY at a price. `amount` alone would
          // set qty to 1 and lose the pieces coverage counts.
          qty: c.qty_supplied,
          unit_price: c.unit_price,
          mpn: c.mpn,
          lcsc: c.lcsc,
          plan_key: "pcba:parts",
          run_id: li.run_id,
          notes: `Supplied by the factory (${c.source}). ${c.qty_supplied} billed at `
               + `${c.unit_price}`
               + (c.qty_from_pool ? `; ${c.qty_from_pool} of this position came from our pool` : "")
               + (c.supplier_mismatch
                  ? "; SUPPLIER NUMBERS DISAGREE — its coverage is unverified" : ""),
        })), { replace: true, allow_parts: true });
      await resolveDocumentParts(li.document_id);
      setCollapsed((c) => { const n = new Set(c); n.delete(li.id); return n; });
      onSaved?.();
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(null);
    }
  };

  const patch = (key: string, next: Partial<LineDraft>) =>
    setRows(rows.map((r) => (r.key === key ? { ...r, ...next } : r)));





  return (
    <>
      {loadError ? <ErrorBanner message={loadError} /> : null}
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
              <th className="ctr">{draftMode ? "" : "Split"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.filter((d) => !hidden(d)).map((d) => {
              const saved = d.id != null ? savedById?.get(d.id) : undefined;
              const header = !!saved?.is_header;
              const away = gone(d);
              const edit = open && !header && !away;
              const amount = saved && !edit
                ? saved.line_total
                : Number(d.qty || 0) * Number(d.unit_price || 0);
              return (
                <tr key={d.key} className={header ? "muted" : away ? "row-gone" : undefined}>
                  <td>
                    {edit ? (
                      <select
                        className="row-input"
                        value={d.kind}
                        onChange={(e) => patch(d.key, { kind: e.target.value as CostLineKind })}
                      >
                        {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                      </select>
                    ) : d.kind}
                  </td>
                  <td title={d.component_name || d.mpn || d.label}>
                    {/* Position IS the identity. For a part that means the
                        library component, not a typed label — the pool keys on
                        the component, and the designators a position covers are
                        not something anybody reads here (user 2026-09-19). */}
                    {header && d.id != null ? (
                      <>
                        <span className={`tree-indent tree-indent-${Math.min(d.depth, 3)}`} />
                        <button
                          type="button"
                          className="btn btn-sm"
                          title="Show or hide the shares this position is split into"
                          onClick={() => toggle(d.id as number)}
                        >
                          {collapsed.has(d.id) ? "▸" : "▾"} {childCount(d.id)}{" "}
                          {partsHeader(d.id) ? "parts" : "shares"}
                        </button>{" "}
                        {d.label || "—"}
                      </>
                    ) : d.kind === "part"
                        && savedById?.get(d.id ?? -1)?.allocate !== "excluded" ? (
                      <>
                        <span className={`tree-indent tree-indent-${Math.min(d.depth, 3)}`} />
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={busy || !edit}
                          title={d.component_id
                            ? "Linked to a library component — click to change or unlink"
                            : "Not linked: this line keys the pool by its MPN string, so it can never meet a BOM draw"}
                          onClick={() => setPicking(d)}
                        >
                          {d.component_name || d.mpn
                            || (d.component_id ? `#${d.component_id}` : "— part —")}
                        </button>
                      </>
                    ) : edit ? (
                      <input
                        className="row-input"
                        value={d.label}
                        onChange={(e) => patch(d.key, { label: e.target.value })}
                      />
                    ) : (
                      <>
                        <span className={`tree-indent tree-indent-${Math.min(d.depth, 3)}`} />
                        {d.label || "—"}
                      </>
                    )}
                  </td>
                  <td className="num">
                    {edit ? (
                      <input
                        className="row-input num"
                        inputMode="decimal"
                        value={d.qty}
                        onChange={(e) => patch(d.key, { qty: e.target.value })}
                      />
                    ) : (saved?.qty_effective ?? d.qty)}
                  </td>
                  <td className="num">
                    {edit ? (
                      <input
                        className="row-input num"
                        inputMode="decimal"
                        value={d.unit_price}
                        onChange={(e) => patch(d.key, { unit_price: e.target.value })}
                      />
                    ) : d.unit_price}
                  </td>
                  <td
                    className="num"
                    title={header ? "split — the shares below carry this money" : undefined}
                  >
                    {plain(amount ?? 0)}
                    {header ? (
                      <>
                        {" "}
                        <span className="pill neutral">split</span>
                        {saved?.residual ? (
                          <span className="pill warn">{plain(saved.residual)} left</span>
                        ) : null}
                      </>
                    ) : null}
                  </td>
                  <td>
                    {header ? (
                      <span className="dim">shares below</span>
                    ) : !edit && saved && saved.kind === "part" && !saved.run_id
                        && saved.allocate !== "excluded" ? (
                      <span className="dim" title="parts feed the shared pool; runs draw from it">
                        pool
                      </span>
                    ) : !edit && saved
                        && (saved.allocate === "by_value" || saved.allocate === "by_qty")
                        && !saved.run_id && !saved.project_id ? (
                      <span
                        className="dim"
                        title={"landed cost — spread " +
                          (saved.allocate === "by_value" ? "by value" : "by quantity") +
                          " over this document's part lines, so it raises their pool unit cost"}
                      >
                        pool (spread)
                      </span>
                    ) : (
                      <ChargeToSelect
                        runs={runs}
                        projects={projects}
                        value={d.dest}
                        disabled={busy || !edit}
                        onChange={(v) => patch(d.key, { dest: v })}
                      />
                    )}
                  </td>
                  <td title={d.plan_ref || ""}>
                    {header ? (
                      <span className="dim">—</span>
                    ) : (
                      <StepSelect
                        catalog={stepCatalog}
                        className="row-input mono"
                        disabled={busy || !edit}
                        value={d.plan_key && d.plan_key.includes(":") ? d.plan_key : ""}
                        title="production step — invoice money billed under a step is matched to the planned cost item carrying the same step automatically"
                        onChange={(v) => patch(d.key, { plan_key: v })}
                      />
                    )}
                  </td>
                  <td className="ctr">
                    {draftMode ? (
                      <button
                        type="button"
                        className="btn btn-sm row-del"
                        onClick={() => setRows(rows.filter((r) => r.key !== d.key))}
                      >
                        ×
                      </button>
                    ) : away ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        title="keep this position after all"
                        onClick={() => {
                          const n = new Set(deleted);
                          n.delete(d.id as number);
                          setDeleted?.(n);
                        }}
                      >
                        undo
                      </button>
                    ) : edit ? (
                      <button
                        type="button"
                        className="btn btn-sm row-del"
                        title="void this position when the batch is saved"
                        onClick={() => setDeleted?.(new Set(deleted).add(d.id as number))}
                      >
                        ×
                      </button>
                    ) : saved && partsHeader(d.id) ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={busy || loading === d.id}
                        title="Fill this position from the supplier's own BOM, one row per part"
                        onClick={() => void loadSupplier(saved)}
                      >
                        {loading === d.id ? "…" : "supplier"}
                      </button>
                    ) : saved ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={busy}
                        onClick={() => onSplit?.(saved)}
                      >
                        split
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="btn-row">
        <button
          type="button"
          className="btn btn-sm"
          disabled={busy || !open}
          onClick={() => setRows([...rows, blankDraft()])}
        >
          Add position
        </button>
        <span className="muted">
          {rows.length} position{rows.length === 1 ? "" : "s"} · {currency}
        </span>
      </div>

      {picking ? (
        <ComponentPickDialog
          line={asRow(picking)}
          allowFreeText
          onPick={(componentId, mpn) =>
            patch(picking.key, {
              component_id: componentId,
              mpn,
              component_name: componentId ? picking.component_name : "",
            })}
          onClose={() => setPicking(null)}
        />
      ) : null}
    </>
  );
}
