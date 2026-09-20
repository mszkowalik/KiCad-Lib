/** Split one invoice position into shares.
 *
 *  Two jobs, one editor: dividing a position between runs, and breaking a
 *  supplier's single printed figure into the sub-fees it is made of (JLC prints
 *  "SMT Assembly $101.04"; stencil / manual assembly / surcharges appear only on
 *  their website).
 *
 *  A share of a PART position names a library component instead of carrying a
 *  typed label, and is a QUANTITY at a price rather than a percentage of a
 *  figure: the pool keys on the component and coverage counts pieces, so a
 *  share typed as text with no quantity can meet neither. Filling a
 *  supplier-parts position from the supplier's own BOM does NOT happen here —
 *  it is one button on the position itself, and the children then edit in place
 *  (decision 0041).
 *
 *  Percentages are a CALCULATOR here, never storage (user decision 2026-07-27):
 *  typing one writes the absolute amount into the row immediately, and only the
 *  absolute travels to the API — so a stored figure can never drift from a
 *  percentage re-derived against a changed base.
 */
import { useEffect, useMemo, useState } from "react";
import { PART_STEPS } from "./InvoiceLinesTable";
import {
  errorMessage,
  getCostSteps,
  resolveDocumentParts,
  splitCostLine,
  type CostStepCatalog,
  type RunCostDocumentRow,
  type RunCostLineRow,
  type SplitChild,
} from "../../api";
import { ErrorBanner } from "../Ui";
import ComponentPickDialog from "../ComponentPickDialog";
import {
  ChargeToSelect,
  ExcludeReasonInput,
  StepSelect,
  type RunOption,
} from "../costs";
import { useModal } from "../modal";

/** Templates come from the production-step catalog (`/api/cost-steps`): the
 *  vendor's exact wording paired with the vendor-neutral step key, so a split
 *  carries its identity and plan-vs-actual matching needs no manual linking. */

export type { RunOption };

interface Row {
  label: string;
  /** part shares only: the library component this share bought */
  component_id: number | null;
  component_name: string;
  mpn: string;
  lcsc: string;
  amount: string;
  /** parts only: a component share is a QUANTITY at a price, never a percentage
   *  of a figure. The amount is computed from these and is not typed. */
  qty: string;
  unit: string;
  percent: string;
  /** production-step key ("pcba:setup"); becomes the child's plan_key */
  step: string;
  /** "" | "run:<id>" | "project:<id>" | "excluded" */
  dest: string;
  /** WHY, when `dest` is "excluded". The API refuses an exclusion without it. */
  reason: string;
  notes: string;
}

function emptyRow(): Row {
  return { label: "", component_id: null, component_name: "", mpn: "", lcsc: "",
           amount: "", qty: "", unit: "", percent: "", step: "", dest: "",
           reason: "", notes: "" };
}

function num(s: string): number {
  const v = Number(s);
  return Number.isFinite(v) ? v : 0;
}

/** Trailing-zero-free fixed formatting, so a computed share reads like a price. */
function fmt(v: number): string {
  return String(Number(v.toFixed(4)));
}

export default function SplitLineDialog({
  line, parentAmount, currency, runs, projects, existing, onClose,
}: {
  line: RunCostLineRow;
  parentAmount: number;
  currency: string;
  runs: RunOption[];
  projects: { id: number; name: string }[];
  existing: RunCostLineRow[];
  onClose: (doc: RunCostDocumentRow | null) => void;
}) {
  const modal = useModal(() => onClose(null));
  const [rows, setRows] = useState<Row[]>(() =>
    existing.length
      ? existing.map((c) => ({
          label: c.label,
          component_id: c.component_id,
          component_name: c.component_name || "",
          mpn: c.mpn || "",
          lcsc: c.lcsc || "",
          amount: fmt(c.line_total ?? 0),
          qty: fmt(c.qty ?? 0),
          unit: fmt(c.unit_price ?? 0),
          percent: parentAmount ? fmt(((c.line_total ?? 0) / parentAmount) * 100) : "",
          step: c.plan_key && c.plan_key.includes(":") ? c.plan_key : "",
          dest: c.allocate === "excluded"
            ? "excluded"
            : c.run_id ? `run:${c.run_id}` : c.project_id ? `project:${c.project_id}` : "",
          reason: c.exclude_reason || "",
          notes: c.notes,
        }))
      : [emptyRow(), emptyRow()],
  );
  const [replace, setReplace] = useState(existing.length > 0);
  const [allowParts, setAllowParts] = useState(false);
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const allocated = useMemo(() => rows.reduce((s, r) => s + num(r.amount), 0), [rows]);
  const residual = parentAmount - allocated;
  const over = residual < -0.005;

  const patch = (i: number, next: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...next } : r)));

  /** A percentage is applied at once and forgotten — the amount is the record. */
  const setPercent = (i: number, pct: string) =>
    patch(i, { percent: pct, amount: pct.trim() === "" ? "" : fmt((parentAmount * num(pct)) / 100) });

  const setAmount = (i: number, amount: string) =>
    patch(i, {
      amount,
      percent: parentAmount && amount.trim() !== "" ? fmt((num(amount) / parentAmount) * 100) : "",
    });

  /** Put whatever is left on the last row, so rounding never leaks a cent. */
  const balanceLast = () => {
    if (!rows.length) return;
    const others = rows.slice(0, -1).reduce((s, r) => s + num(r.amount), 0);
    setAmount(rows.length - 1, fmt(Math.max(parentAmount - others, 0)));
  };

  const splitEvenly = () => {
    const n = rows.length;
    if (!n) return;
    const each = Number((parentAmount / n).toFixed(4));
    setRows((rs) =>
      rs.map((r, i) => {
        // last row absorbs the rounding remainder
        const amount = i === n - 1 ? parentAmount - each * (n - 1) : each;
        return { ...r, amount: fmt(amount), percent: fmt((amount / parentAmount) * 100) };
      }),
    );
  };

  const [catalog, setCatalog] = useState<CostStepCatalog | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    getCostSteps(ac.signal).then(setCatalog).catch(() => setCatalog(null));
    return () => ac.abort();
  }, []);


  // A stock position: the STEP says so now, not a second `kind` field
  // (decision 0047).
  const isPart = PART_STEPS.has(line.plan_key || "");
  // Charged to a batch and stepped as its parts: never pool stock.
  const supplierLump = isPart && line.plan_key === "pcba:parts" && !!line.run_id;


  const addTemplate = (name: string) => {
    const tpl = catalog?.templates[name];
    if (!tpl) return;
    setRows((rs) => [
      ...rs.filter((r) => r.label.trim() !== "" || r.amount.trim() !== ""),
      ...tpl.map((t) => ({ ...emptyRow(), label: t.label, step: t.step,
                           })),
    ]);
  };

  const save = async () => {
    const usable = rows.filter((r) => isPart
      ? (r.mpn.trim() !== "" || r.component_id != null || num(r.qty) !== 0)
      : (r.label.trim() !== "" || num(r.amount) !== 0));
    if (!usable.length) {
      setError("Add at least one share with a label or an amount.");
      return;
    }
    // The API refuses this too, but a share charged to nobody is exactly the
    // one a person walks away from: it needs no batch, no project and no
    // further thought, so the prompt has to arrive before the save.
    if (usable.some((r) => r.dest === "excluded" && !r.reason.trim())) {
      setError("A share charged to nobody has to say why — fill the reason beside it.");
      return;
    }
    const children: SplitChild[] = usable.map((r) => {
      const [kind, id] = r.dest ? r.dest.split(":") : ["", ""];
      return {
        label: r.label.trim() || r.component_name || r.mpn || line.label,
        component_id: r.component_id,
        mpn: r.mpn.trim(),
        lcsc: r.lcsc.trim(),
        // A component share carries its real quantity — coverage counts pieces,
        // and `amount` alone would set qty to 1 and lose them.
        ...(isPart
          ? { qty: num(r.qty), unit_price: num(r.unit) }
          : { amount: num(r.amount) }),
        plan_key: r.step || undefined,
        // "excluded" records the share for reconciliation without charging it —
        // and says what for, because an exclusion nobody explained passes every
        // other check the register has (decision 0048).
        allocate: r.dest === "excluded" ? "excluded" : undefined,
        exclude_reason: r.dest === "excluded" ? r.reason.trim() : undefined,
        run_id: kind === "run" ? Number(id) : null,
        project_id: kind === "project" ? Number(id) : null,
        notes: r.notes.trim(),
      };
    });
    setBusy(true);
    setError(null);
    try {
      const res = await splitCostLine(line.id, children, { replace, allow_parts: allowParts });
      // A part share keyed only by MPN can never meet a BOM draw. The importer
      // resolves on every write; a hand-made split has to do the same or the
      // two paths produce different rows from the same facts.
      if (children.some((c) => PART_STEPS.has(c.plan_key || ""))) {
        try {
          await resolveDocumentParts(line.document_id);
        } catch {
          /* resolution is a bridge, not the write — never lose the split over it */
        }
      }
      onClose(res.document);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">Split “{line.label || line.kind}”</h2>
        <p className="card-subtitle">
          {fmt(parentAmount)} {currency} on the invoice. The position keeps that figure — the shares
          below carry the money, so nothing is counted twice. Leaving some unallocated is fine; it
          shows up as a residual.
        </p>

        {error ? <ErrorBanner message={error} /> : null}

        <div className="table-wrap split-rows-scroll">
          <table className="data data-fixed split-rows-table">
            <thead>
              <tr>
                <th>{isPart ? "Part" : "Label"}</th>
                {isPart ? (
                  <>
                    <th className="num">Qty</th>
                    <th className="num">Unit</th>
                  </>
                ) : (
                  <>
                    <th className="num">Amount</th>
                    <th className="num">%</th>
                  </>
                )}
                <th>What it is</th>
                <th>Goes to</th>
                <th>Note</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    {/* A share of a PART position names a component: the pool
                        keys on it, and a share typed as text can never meet a
                        BOM draw. Free text stays available because a part the
                        SUPPLIER provided off its own shelf legitimately has no
                        library entry. */}
                    {isPart ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={busy}
                        title={r.component_id
                          ? "Linked to a library component"
                          : "Not linked — this share will key the pool by its MPN string"}
                        onClick={() => setPicking(i)}
                      >
                        {r.component_name || r.mpn || r.label || "— part —"}
                      </button>
                    ) : (
                      <input
                        className="row-input"
                        value={r.label}
                        placeholder={line.label}
                        disabled={busy}
                        onChange={(e) => patch(i, { label: e.target.value })}
                      />
                    )}
                  </td>
                  {/* Components are counted, not sliced. A percentage of a
                      printed figure is the right tool for dividing one position
                      between two batches and the wrong one for a parts list
                      (user report 2026-09-19). */}
                  {isPart ? (
                    <>
                      <td>
                        <input
                          className="row-input num"
                          inputMode="decimal"
                          value={r.qty}
                          disabled={busy}
                          onChange={(e) => patch(i, {
                            qty: e.target.value,
                            amount: fmt(num(e.target.value) * num(r.unit)),
                          })}
                        />
                      </td>
                      <td>
                        <input
                          className="row-input num"
                          inputMode="decimal"
                          value={r.unit}
                          disabled={busy}
                          onChange={(e) => patch(i, {
                            unit: e.target.value,
                            amount: fmt(num(r.qty) * num(e.target.value)),
                          })}
                        />
                      </td>
                    </>
                  ) : (
                    <>
                      <td>
                        <input
                          className="row-input num"
                          inputMode="decimal"
                          value={r.amount}
                          onChange={(e) => setAmount(i, e.target.value)}
                        />
                      </td>
                      <td>
                        <input
                          className="row-input num"
                          inputMode="decimal"
                          placeholder="%"
                          value={r.percent}
                          onChange={(e) => setPercent(i, e.target.value)}
                        />
                      </td>
                    </>
                  )}
                  <td>
                    <StepSelect
                      catalog={catalog}
                      className="row-input mono"
                      value={r.step}
                      emptyLabel="—"
                      title="production step — carries into plan_key so plan-vs-billed matches automatically"
                      onChange={(step) => patch(i, { step })}
                    />
                  </td>
                  <td>
                    <ChargeToSelect
                      runs={runs}
                      projects={projects}
                      value={r.dest}
                      emptyLabel="— nobody yet —"
                      onChange={(dest) => patch(i, { dest })}
                    />
                    {/* Under the destination, not in its own column: it only
                        applies to one choice, and a column that is empty on
                        every other row costs width the table does not have. */}
                    {r.dest === "excluded" ? (
                      <ExcludeReasonInput
                        value={r.reason}
                        onChange={(reason) => patch(i, { reason })}
                      />
                    ) : null}
                  </td>
                  <td>
                    <input
                      className="row-input"
                      value={r.notes}
                      onChange={(e) => patch(i, { notes: e.target.value })}
                    />
                  </td>
                  <td className="ctr">
                    <button
                      type="button"
                      className="btn btn-sm row-del"
                      title="Remove this share"
                      onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
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
          <button type="button" className="btn btn-sm" onClick={() => setRows((rs) => [...rs, emptyRow()])}>
            Add share
          </button>
          {/* Both divide a printed FIGURE. Neither means anything on a parts
              list, where each row is a quantity at a price. */}
          {isPart ? null : (
            <>
              <button type="button" className="btn btn-sm" onClick={splitEvenly}>
                Split evenly
              </button>
              <button type="button" className="btn btn-sm" onClick={balanceLast}>
                Balance last row
              </button>
            </>
          )}
          {Object.keys(catalog?.templates ?? {}).map((name) => (
            <button key={name} type="button" className="btn btn-sm"
                    onClick={() => addTemplate(name)}
                    title="Insert these steps — each row carries its production-step key, so plan-vs-actual matches automatically">
              {name}
            </button>
          ))}
        </div>

        <p className={over ? "banner-error" : "muted"}>
          Allocated {fmt(allocated)} of {fmt(parentAmount)} {currency} ·{" "}
          {over ? (
            <>over by {fmt(-residual)} — the API will refuse this</>
          ) : (
            <>residual {fmt(residual)}</>
          )}
        </p>

        {existing.length ? (
          <label className="muted">
            <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />{" "}
            Replace the {existing.length} existing share{existing.length === 1 ? "" : "s"} (they are
            voided, not deleted)
          </label>
        ) : null}
        {/* The warning is about a POOLED purchase. A supplier-parts lump is the
            opposite case — it is charged to the batch and never pooled — so
            saying "parts feed the shared pool" there is simply wrong (user
            report 2026-09-19). */}
        {isPart && supplierLump ? (
          <div className="muted">
            These parts came off the supplier's own shelf, so the shares stay charged to this
            batch and never enter the shared pool — their price belongs to this one order.
            <label className="muted">
              <input
                type="checkbox"
                checked={allowParts}
                onChange={(e) => setAllowParts(e.target.checked)}
              />{" "}
              Split this parts position
            </label>
          </div>
        ) : isPart ? (
          <div className="banner-warn">
            This is a component purchase that feeds the shared pool, and the pool is already split
            by what each run consumes — splitting one per run double counts. Only override this for
            parts bought for a single batch, which stay out of the pool.
            <label className="muted">
              <input
                type="checkbox"
                checked={allowParts}
                onChange={(e) => setAllowParts(e.target.checked)}
              />{" "}
              I know: split this part line anyway
            </label>
          </div>
        ) : null}

        <div className="btn-row modal-actions">
          <button type="button" className="btn" onClick={() => onClose(null)} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={save} disabled={busy || over}>
            {busy ? "Splitting…" : "Split"}
          </button>
        </div>
      </div>
      {picking !== null ? (
        <ComponentPickDialog
          line={{
            label: rows[picking]?.label,
            mpn: rows[picking]?.mpn,
            component_id: rows[picking]?.component_id,
            component_name: rows[picking]?.component_name,
          }}
          allowFreeText
          title="Which part did this share buy?"
          confirmLabel="Use this part"
          onPick={(componentId, mpn) => {
            const i = picking;
            setRows((rs) => rs.map((r, j) => (j === i
              ? { ...r, component_id: componentId, mpn, component_name: componentId ? mpn : "" }
              : r)));
          }}
          onClose={() => setPicking(null)}
        />
      ) : null}
    </div>
  );
}
