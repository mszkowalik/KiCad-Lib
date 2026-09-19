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
  type CostStepCatalog,
  type RunCostLineRow,
} from "../../api";
import { plain } from "../../format";
import { GoesToSelect, HowSelect, StepSelect, type RunOption } from "../costs";
import ComponentPickDialog from "../ComponentPickDialog";
import { ErrorBanner } from "../Ui";

/** The production steps whose money is STOCK (decision 0047). Mirrors
 *  `cost_steps.PART_STEPS`; the catalog is the source, this is the browser's
 *  copy of the same four keys for the handful of places that cannot wait for it
 *  to load. */
export const PART_STEPS = new Set([
  "parts:pool", "parts:prepaid", "parts:attrition", "pcba:parts",
]);

export const isPartStep = (step: string) => PART_STEPS.has(step);

/** COLUMN WIDTHS. On the header cells, not in styles.css.
 *
 *  They were `nth-child` rules and had been wrong five times: adding or removing
 *  a column shifts every rule after it, silently. They are here so a column
 *  added without a width is visible in the same glance as the `<th>` — and
 *  because a `<colgroup>` was tried first and did not win against whatever
 *  styles the cells, while an inline style on the first row always does under
 *  `table-layout: fixed`.
 *
 *  MEASURED in the browser at a 1250px table, as "what the widest option in
 *  that column needs" (px): What it is 154 · Qty 72 · Unit 87 · Goes to 289 ·
 *  How 156. Position is deliberately short — a component name has no upper
 *  bound, so it ellipsises and carries a title. They sum to 100.
 */
const W = {
  what:     { width: "13%" },
  position: { width: "22%" },
  qty:      { width: "6%" },
  unit:     { width: "7%" },
  amount:   { width: "8%" },
  goesTo:   { width: "24%" },
  how:      { width: "15%" },
  split:    { width: "5%" },
} as const;

/** A row while it is being typed into. Amounts stay STRINGS so a half-typed
 *  "1." is not rounded away under the cursor. */
export interface LineDraft {
  key: string;
  id: number | null;          // null => a row that does not exist server-side yet
  label: string;
  mpn: string;
  qty: string;
  unit_price: string;
  component_id: number | null;
  component_name: string;
  plan_key: string;
  plan_kind: string;
  plan_ref: string;
  /** WHERE the money goes: "" (not decided) | "inherit" | "pool" |
   *  "run:5" | "project:2" | "nobody" — see `GoesToSelect` (decision 0045). */
  dest: string;
  /** HOW it gets there. Carries `allocate` when `dest` is "pool"
   *  ("pooled" | "by_value" | "by_qty") and `basis` when it is a batch or a
   *  project ("per_run" | "per_device"). Unused for "nobody", which takes a
   *  typed reason instead. */
  how: string;
  /** why this position is charged to nobody — only when `dest` is "nobody" */
  exclude_reason: string;
  /** tree depth, computed by the caller from parent_line_id */
  depth: number;
}

let seq = 0;
export function blankDraft(): LineDraft {
  seq += 1;
  return {
    key: `new-${seq}`, id: null, label: "", mpn: "",
    qty: "1", unit_price: "", component_id: null, component_name: "",
    plan_key: "", plan_kind: "", plan_ref: "", dest: "", how: "per_run",
    exclude_reason: "", depth: 0,
  };
}

/** The stored line as the two questions the UI asks.
 *
 *  It MIRRORS `run_actuals.line_destination`, including its order — `excluded`
 *  beats a named run, and a named run beats a `part` line's implicit pool — so
 *  what the row shows is what the server will compute. Any drift here shows a
 *  destination the money does not actually go to, which is the failure this
 *  whole change exists to end.
 */
export function goesToOf(li: RunCostLineRow): string {
  if (li.allocate === "excluded") return "nobody";
  if (li.run_id) return `run:${li.run_id}`;
  if (li.project_id) return `project:${li.project_id}`;
  if (li.allocate === "pooled" || li.allocate === "by_value" || li.allocate === "by_qty") {
    return "pool";
  }
  // A `part` line written before `pooled` existed. It resolves to the pool on
  // the server, so it has to read that way here; the backfill has already
  // marked the ones that were reachable, and this covers a line whose document
  // names a run (which the server charges to that run, not to stock).
  if (isPartStep(li.plan_key || "")) return "pool";
  // Nothing says where this goes, and nothing can be inferred. On a document
  // that names a destination the caller turns this into "inherit"; otherwise it
  // is genuinely undecided, and the register reports it as unassigned.
  return "";
}

export function toDraft(li: RunCostLineRow, depth = 0, docHasDefault = false): LineDraft {
  const dest = goesToOf(li);
  return {
    key: `line-${li.id}`,
    id: li.id,
    label: li.label,
    mpn: li.mpn || "",
    qty: String(li.qty ?? ""),
    unit_price: String(li.unit_price ?? ""),
    component_id: li.component_id,
    component_name: li.component_name || "",
    plan_key: li.plan_key || "",
    plan_kind: li.plan_kind || "",
    plan_ref: li.plan_ref || "",
    dest: dest === "" && docHasDefault ? "inherit" : dest,
    how: dest === "pool"
      ? (li.allocate === "by_value" || li.allocate === "by_qty" ? li.allocate : "pooled")
      : (li.basis || "per_run"),
    exclude_reason: li.exclude_reason || "",
    depth,
  };
}

/** The line as a fake `RunCostLineRow`, so the component dialog can be reused
 *  by a draft row that has no server id yet. */
function asRow(d: LineDraft): RunCostLineRow {
  return {
    id: d.id ?? -1, document_id: -1, run_id: null, position: 0,
    basis: "per_run", label: d.label, qty: Number(d.qty || 0),
    unit_price: Number(d.unit_price || 0), line_total: null, currency: "",
    allocate: "none", component_id: d.component_id, component_name: d.component_name,
    mpn: d.mpn, lcsc: "", description: "", plan_key: d.plan_key, plan_kind: d.plan_kind,
    notes: "",
  } as RunCostLineRow;
}

/** The two answers as the three fields the server stores.
 *
 *  ALWAYS writes all four of `run_id`, `project_id`, `allocate` and `basis`,
 *  never a subset. The version this replaces only ever ADDED
 *  `allocate: "excluded"` and never cleared it, so moving an excluded position
 *  onto a batch left `allocate` behind — and `line_destination` tests
 *  `excluded` before it tests `run_id`, so the line stayed charged to nobody
 *  while the screen showed the batch.
 */
function destPatch(d: LineDraft) {
  const [kind, id] = d.dest.includes(":") ? d.dest.split(":") : ["", ""];
  const spread = d.how === "by_value" || d.how === "by_qty";
  return {
    // "inherit" stores nothing and lets the DOCUMENT's destination apply, which
    // is what the line already did. It is a visible way to say so, not a change.
    run_id: kind === "run" ? Number(id) : null,
    project_id: kind === "project" ? Number(id) : null,
    allocate:
      d.dest === "nobody" ? "excluded"
      : d.dest === "pool" ? (spread ? d.how : "pooled")
      : "none",
    // Only a position charged to a batch or a project can be billed per device;
    // stock and excluded money have no units to multiply by.
    basis: (d.dest === "pool" || d.dest === "nobody" || d.dest === ""
            ? "per_run"
            : d.how === "per_device" ? "per_device" : "per_run") as "per_run" | "per_device",
    exclude_reason: d.dest === "nobody" ? d.exclude_reason.trim() : "",
  };
}

export function draftToLineIn(d: LineDraft) {
  return {
    label: d.label.trim(),
    mpn: d.mpn.trim(),
    qty: Number(d.qty || 0),
    unit_price: Number(d.unit_price || 0),
    component_id: d.component_id,
    plan_key: d.plan_key,
    plan_kind: d.plan_kind,
    plan_ref: d.plan_ref,
    ...destPatch(d),
  };
}

export default function InvoiceLinesTable({
  mode, rows, setRows, runs, projects, stepCatalog, currency,
  editing, deleted, setDeleted, savedById, onSplit, onSaved, busy, locked,
  docDefault = "",
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
  /** What the DOCUMENT itself charges to, worded — "Batch 8", "CE_Dongle_V2".
   *  Empty when it names nothing. A line that stores no destination of its own
   *  falls back to this on the server, so the row offers it as "from this
   *  document (…)" rather than showing the same blank that means "undecided". */
  docDefault?: string;
  /** saved mode: this document charges a CLOSED batch (decision 0044), so the
   *  server refuses every write to it. `split` and `supplier` fire immediately
   *  rather than staging into the batch save, so they have to be stopped HERE —
   *  a button that only ever produces a 409 is worse than one that is not there. */
  locked?: boolean;
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
      .filter((id) => isPartStep(savedById?.get(id)?.plan_key || ""))));
  }, [headerIds]);

  const childCount = (id: number) => savedById
    ? [...savedById.values()].filter((x) => x.parent_line_id === id && !x.voided).length
    : 0;
  const partsHeader = (id: number | null) => {
    if (id == null) return false;
    const li = savedById?.get(id);
    return !!li?.is_header && isPartStep(li.plan_key || "");
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
              {/* "Planned as" was a poor name for it even when there were two
                  columns: the step is not a plan, it is what the position IS. */}
              <th style={W.what}>What it is</th>
              <th style={W.position}>Position</th>
              <th className="num" style={W.qty}>Qty</th>
              <th className="num" style={W.unit}>Unit</th>
              <th className="num" style={W.amount}>Amount</th>
              {/* "Charge to" was wrong for the commonest answer: nothing is
                  charged when a position becomes stock. "Goes to" covers a
                  batch and the shelf equally. */}
              <th style={W.goesTo}>Goes to</th>
              <th style={W.how}>How</th>
              <th className="ctr" style={W.split}>{draftMode ? "" : "Split"}</th>
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
                  {/* WHAT THIS POSITION IS. One field, not two: `kind` was a
                      coarser second answer typed beside this one and free to
                      disagree with it (decision 0047). The bucket every report
                      still wants is derived from the step on the server. */}
                  <td title={d.plan_ref || ""}>
                    {header ? (
                      <span className="dim">—</span>
                    ) : (
                      <StepSelect
                        catalog={stepCatalog}
                        className={`row-input mono${d.plan_key ? "" : " needs-answer"}`}
                        disabled={busy || !edit}
                        value={d.plan_key && d.plan_key.includes(":") ? d.plan_key : ""}
                        title={d.plan_key
                          ? "What this position is. Money billed under a step is matched "
                            + "to the planned cost item carrying the same step automatically."
                          : "This position has not said what it is."}
                        onChange={(v) => {
                          // SUGGEST where it goes, and only into an empty box —
                          // never overwrite an answer. A stock step IS the
                          // instruction to pool it; that used to be hidden
                          // inside `kind` (decisions 0045, 0047).
                          const stock = isPartStep(v);
                          const suggest = d.dest !== "" ? {}
                            : stock ? { dest: "pool", how: "pooled" }
                            : v === "logistics:inbound" || v === "logistics:duty"
                              ? { dest: "pool", how: "by_value" }
                            // A cancelled line has no destination: the supplier
                            // printed it, nothing was delivered, nobody pays
                            // (user decision 2026-09-19). Same for a payment fee,
                            // which is real money attributable to no product.
                            : v === "other:cancelled"
                              ? { dest: "nobody", exclude_reason: "cancelled_by_supplier" }
                            : v === "other:payment_fee"
                              ? { dest: "nobody", exclude_reason: "payment_fee" }
                            : {};
                          // REPAIR an answer the new step has made illegal: only
                          // a stock position can BE stock. Without this the
                          // select fell back to the first legal option in the
                          // DOM while React still held "pooled", and the row
                          // SAVED as stock — a pool entry with no part behind it.
                          const repair = !stock && d.how === "pooled"
                            ? { how: "by_value" } : {};
                          patch(d.key, { plan_key: v, ...suggest, ...repair });
                        }}
                      />
                    )}
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
                    ) : isPartStep(d.plan_key)
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
                  {/* THE TWO QUESTIONS (decision 0045). Where the money goes,
                      and how it gets there. The read-only spellings that used to
                      live here — "pool", "pool (spread)" — are gone: the select
                      now shows the same answer whether or not the document is
                      open for editing, so there is one wording to keep true
                      instead of three. */}
                  <td>
                    {header ? (
                      <span className="dim">shares below</span>
                    ) : (
                      <GoesToSelect
                        runs={runs}
                        projects={projects}
                        value={d.dest}
                        docDefault={docDefault}
                        disabled={busy || !edit}
                        onChange={(v) => patch(d.key, {
                          dest: v,
                          // The second question changes meaning with the first,
                          // so its answer cannot carry across. Default to the
                          // ordinary case for the destination just chosen.
                          how: v === "pool"
                            ? (isPartStep(d.plan_key) ? "pooled" : "by_value")
                            : "per_run",
                        })}
                      />
                    )}
                  </td>
                  <td>
                    {header ? (
                      <span className="dim">—</span>
                    ) : (
                      <HowSelect
                        goesTo={d.dest}
                        value={d.how}
                        reason={d.exclude_reason}
                        isPart={isPartStep(d.plan_key)}
                        disabled={busy || !edit}
                        onChange={(v) => patch(d.key, { how: v })}
                        onReasonChange={(v) => patch(d.key, { exclude_reason: v })}
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
                        disabled={busy || locked || loading === d.id}
                        title={locked
                          ? "The books are closed on this batch — correct it with a new document"
                          : "Fill this position from the supplier's own BOM, one row per part"}
                        onClick={() => void loadSupplier(saved)}
                      >
                        {loading === d.id ? "…" : "supplier"}
                      </button>
                    ) : saved ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={busy || locked}
                        title={locked
                          ? "The books are closed on this batch — correct it with a new document"
                          : undefined}
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
