/** Split one invoice position into shares.
 *
 *  Two jobs, one editor: dividing a position between runs, and breaking a
 *  supplier's single printed figure into the sub-fees it is made of (JLC prints
 *  "SMT Assembly $101.04"; stencil / manual assembly / surcharges appear only on
 *  their website).
 *
 *  Percentages are a CALCULATOR here, never storage (user decision 2026-07-27):
 *  typing one writes the absolute amount into the row immediately, and only the
 *  absolute travels to the API — so a stored figure can never drift from a
 *  percentage re-derived against a changed base.
 */
import { useEffect, useMemo, useState } from "react";
import {
  errorMessage,
  getCostSteps,
  splitCostLine,
  type CostStepCatalog,
  type CostLineKind,
  type RunCostDocumentRow,
  type RunCostLineRow,
  type SplitChild,
} from "../../api";
import { ErrorBanner } from "../Ui";
import {
  COST_LINE_KINDS as KINDS,
  ChargeToSelect,
  StepSelect,
  type RunOption,
} from "../costs";

/** Templates come from the production-step catalog (`/api/cost-steps`): the
 *  vendor's exact wording paired with the vendor-neutral step key, so a split
 *  carries its identity and plan-vs-actual matching needs no manual linking. */

export type { RunOption };

interface Row {
  label: string;
  amount: string;
  percent: string;
  kind: CostLineKind | "";
  /** production-step key ("pcba:setup"); becomes the child's plan_key */
  step: string;
  /** "" | "run:<id>" | "project:<id>" */
  dest: string;
  notes: string;
}

function emptyRow(): Row {
  return { label: "", amount: "", percent: "", kind: "", step: "", dest: "", notes: "" };
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
  const [rows, setRows] = useState<Row[]>(() =>
    existing.length
      ? existing.map((c) => ({
          label: c.label,
          amount: fmt(c.line_total ?? 0),
          percent: parentAmount ? fmt(((c.line_total ?? 0) / parentAmount) * 100) : "",
          kind: c.kind,
          step: c.plan_key && c.plan_key.includes(":") ? c.plan_key : "",
          dest: c.allocate === "excluded"
            ? "excluded"
            : c.run_id ? `run:${c.run_id}` : c.project_id ? `project:${c.project_id}` : "",
          notes: c.notes,
        }))
      : [emptyRow(), emptyRow()],
  );
  const [replace, setReplace] = useState(existing.length > 0);
  const [allowParts, setAllowParts] = useState(false);
  const [busy, setBusy] = useState(false);
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

  const defaultKindFor = (step: string): CostLineKind | "" =>
    (catalog?.steps.find((st) => st.key === step)?.default_kind as CostLineKind) ?? "";

  const addTemplate = (name: string) => {
    const tpl = catalog?.templates[name];
    if (!tpl) return;
    setRows((rs) => [
      ...rs.filter((r) => r.label.trim() !== "" || r.amount.trim() !== ""),
      ...tpl.map((t) => ({ ...emptyRow(), label: t.label, step: t.step,
                           kind: defaultKindFor(t.step) })),
    ]);
  };

  const save = async () => {
    const usable = rows.filter((r) => r.label.trim() !== "" || num(r.amount) !== 0);
    if (!usable.length) {
      setError("Add at least one share with a label or an amount.");
      return;
    }
    const children: SplitChild[] = usable.map((r) => {
      const [kind, id] = r.dest ? r.dest.split(":") : ["", ""];
      return {
        label: r.label.trim() || line.label,
        amount: num(r.amount),
        kind: (r.kind || (r.step ? defaultKindFor(r.step) : "") || undefined) as CostLineKind | undefined,
        plan_key: r.step || undefined,
        // "excluded" records the share for reconciliation without charging it
        allocate: r.dest === "excluded" ? "excluded" : undefined,
        run_id: kind === "run" ? Number(id) : null,
        project_id: kind === "project" ? Number(id) : null,
        notes: r.notes.trim(),
      };
    });
    setBusy(true);
    setError(null);
    try {
      const res = await splitCostLine(line.id, children, { replace, allow_parts: allowParts });
      onClose(res.document);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose(null)}>
      <div className="card pad modal-card modal-card-wide" onMouseDown={(e) => e.stopPropagation()}>
        <h2 className="card-title">Split “{line.label || line.kind}”</h2>
        <p className="card-subtitle">
          {fmt(parentAmount)} {currency} on the invoice. The position keeps that figure — the shares
          below carry the money, so nothing is counted twice. Leaving some unallocated is fine; it
          shows up as a residual.
        </p>

        {error ? <ErrorBanner message={error} /> : null}

        <div className="table-wrap">
          <table className="data data-fixed split-rows-table">
            <thead>
              <tr>
                <th>Label</th>
                <th className="num">Amount</th>
                <th className="num">%</th>
                <th>Step</th>
                <th>Kind</th>
                <th>Charge to</th>
                <th>Note</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    <input
                      className="row-input"
                      value={r.label}
                      placeholder={line.label}
                      onChange={(e) => patch(i, { label: e.target.value })}
                    />
                  </td>
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
                  <td>
                    <StepSelect
                      catalog={catalog}
                      className="row-input mono"
                      value={r.step}
                      emptyLabel="—"
                      title="production step — carries into plan_key so plan-vs-billed matches automatically"
                      onChange={(step) => patch(i, { step, kind: r.kind || defaultKindFor(step) })}
                    />
                  </td>
                  <td>
                    <select
                      className="row-input"
                      value={r.kind}
                      onChange={(e) => patch(i, { kind: e.target.value as CostLineKind | "" })}
                    >
                      <option value="">{line.kind} (same)</option>
                      {KINDS.map((k) => (
                        <option key={k} value={k}>{k}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <ChargeToSelect
                      runs={runs}
                      projects={projects}
                      value={r.dest}
                      emptyLabel="— nobody yet —"
                      onChange={(dest) => patch(i, { dest })}
                    />
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
          <button type="button" className="btn btn-sm" onClick={splitEvenly}>
            Split evenly
          </button>
          <button type="button" className="btn btn-sm" onClick={balanceLast}>
            Balance last row
          </button>
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
        {line.kind === "part" ? (
          <div className="banner-warn">
            This is a component purchase. Parts feed the shared pool and are already split by what
            each run consumes — splitting one per run double counts. Only override this for parts
            bought for a single batch.
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
    </div>
  );
}
