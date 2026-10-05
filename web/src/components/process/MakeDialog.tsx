/** Make a PREPARED PART by its recipe (decisions 0058 §3, 0059 §3).
 *
 *  Always a dry run first: "Preview" shows every draw with its price, the value
 *  of the lot it will make, and any shortage, and only then "Make it" writes.
 *  The same dialog serves the project's Process tab and a batch page — on a
 *  batch it opens with that batch filled in, which is CONTEXT for the
 *  arithmetic panel and never a charge: the batch pays when it draws the lot.
 *
 *  An internal input (a prepared part) takes its oldest lot first unless one
 *  is picked: that is the only choice a person makes here, because two lots of
 *  one prepared part can differ (printed or stickered, found at zero value or built
 *  from today's purchases). Bought inputs follow the pool's moving average, or
 *  their lots oldest first while lot pricing is on (decision 0073), like every
 *  other draw in the platform.
 */
import { useMemo, useState } from "react";
import {
  errorMessage,
  transformProcess,
  type PreparedRecipe,
  type ProcessVersionDetail,
  type RunInfo,
  type StageLot,
  type TransformPlan,
} from "../../api";
import { usd } from "../../format";
import AutoTextarea from "../AutoTextarea";
import DataTable, { type Column } from "../DataTable";
import Field, { FieldGrid } from "../Field";
import NumberInput from "../NumberInput";
import { ErrorBanner, Spinner } from "../Ui";
import { useModal } from "../modal";

/** Today as YYYY-MM-DD in the LOCAL calendar. `toISOString()` is UTC, so
 *  between midnight and 02:00 in Poland it named yesterday. */
export function today(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function inputsText(r: PreparedRecipe, parts: ProcessVersionDetail["parts"]): string {
  return r.inputs
    .map((i) => `${i.qty} × ${i.component_id ? parts[String(i.component_id)]?.name ?? `part ${i.component_id}` : i.mpn}`)
    .join(" + ");
}

export default function MakeDialog({
  projectId, version, recipe, runs, runId = null, lotsByPart, onClose,
}: {
  projectId: number;
  version: ProcessVersionDetail;
  recipe: PreparedRecipe;
  runs: RunInfo[];
  runId?: number | null;
  /** open lots of every stage, by component id */
  lotsByPart: Record<number, StageLot[]>;
  onClose: (made: boolean) => void;
}) {
  const modal = useModal(() => onClose(false));
  const [qty, setQty] = useState<number | null>(null);
  const [scrap, setScrap] = useState<number | null>(0);
  const [madeAt, setMadeAt] = useState(today());
  const [batch, setBatch] = useState<number | null>(runId);
  const [note, setNote] = useState("");
  // component id -> the lot it takes, or "" = oldest first
  const [lotPick, setLotPick] = useState<Record<number, string>>({});
  const [plan, setPlan] = useState<TransformPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const output = version.parts[String(recipe.output_component_id)];
  // Only library parts can be internal; an input named by MPN is always bought.
  const internalInputs = recipe.inputs
    .filter((i): i is typeof i & { component_id: number } =>
      !!i.component_id && !!version.parts[String(i.component_id)]?.internal);

  const body = () => {
    const units = (qty ?? 0) + (scrap ?? 0);
    const lots: Record<string, { adjustment_id: number; qty: number }[]> = {};
    for (const i of internalInputs) {
      const pick = lotPick[i.component_id];
      if (pick) lots[String(i.component_id)] = [{ adjustment_id: Number(pick), qty: i.qty * units }];
    }
    return {
      recipe_key: recipe.key, qty: qty ?? 0, scrap: scrap ?? 0, made_at: madeAt,
      run_id: batch, version_id: version.id, note,
      lots: Object.keys(lots).length ? lots : null,
    };
  };

  const preview = async () => {
    setBusy(true); setError(null);
    try {
      setPlan(await transformProcess(projectId, { ...body(), dry_run: true }));
    } catch (err) {
      setPlan(null); setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    setBusy(true); setError(null);
    try {
      await transformProcess(projectId, { ...body(), dry_run: false });
      onClose(true);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  // Any change to the inputs makes the shown plan stale.
  const touch = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPlan(null); };

  const columns = useMemo<Column<TransformPlan["draws"][number]>[]>(() => [
    { key: "name", label: "Part", width: 40, get: (d) => d.name },
    { key: "lot", label: "Lot", width: 14, get: (d) => (d.lot_adjustment_id ? `A${d.lot_adjustment_id}` : "pool"),
      className: "mono" },
    { key: "qty", label: "Qty", width: 14, numeric: true, get: (d) => d.qty },
    { key: "unit", label: "Unit", width: 16, numeric: true, get: (d) => d.unit_cost_usd,
      render: (d) => usd(d.unit_cost_usd, 4) },
    { key: "value", label: "Value", width: 16, numeric: true, get: (d) => d.value_usd,
      render: (d) => usd(d.value_usd) },
  ], []);

  const blocked = !!plan && (plan.shortages.length > 0 || plan.problems.length > 0);

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">Make {output?.name ?? recipe.output_component_id}</h2>
        <p className="muted dim">
          {recipe.label || recipe.key}: {inputsText(recipe, version.parts)} for each unit.
          Process v{version.version_no}.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        <FieldGrid>
          <Field label="Good units made">
            <NumberInput className="text" value={qty} min={0} onChange={touch(setQty)} />
          </Field>
          <Field label="Scrapped" hint="units' worth of inputs that broke">
            <NumberInput className="text" value={scrap} min={0} onChange={touch(setScrap)} />
          </Field>
          <Field label="Made on">
            <input className="text" type="date" value={madeAt}
              onChange={(e) => touch(setMadeAt)(e.target.value)} />
          </Field>
          <Field label="For batch" hint="context only — the batch pays when it draws the lot">
            <select className="text" value={batch ?? ""}
              onChange={(e) => touch(setBatch)(e.target.value ? Number(e.target.value) : null)}>
              <option value="">no batch (stock preparation)</option>
              {runs.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </Field>
          {internalInputs.map((i) => {
            const lots = lotsByPart[i.component_id] ?? [];
            return (
              <Field key={i.component_id} label={`Lot of ${version.parts[String(i.component_id)]?.name}`}>
                <select className="text" value={lotPick[i.component_id] ?? ""}
                  onChange={(e) => touch((v: string) => setLotPick({ ...lotPick, [i.component_id]: v }))(e.target.value)}>
                  <option value="">oldest first</option>
                  {lots.map((lt) => (
                    <option key={lt.adjustment_id} value={lt.adjustment_id}>
                      A{lt.adjustment_id} · {lt.remaining} left · {usd(lt.unit_cost_usd)} each
                    </option>
                  ))}
                </select>
              </Field>
            );
          })}
          <Field label="Note" wide>
            <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>

        {plan ? (
          <>
            {plan.shortages.length ? (
              <div className="banner-error">
                Not in stock:{" "}
                {plan.shortages.map((s) => `${s.label} (${s.short} short)`).join(", ")}.
                Enter the missing purchase or record a stock adjustment first.
              </div>
            ) : null}
            {plan.problems.length ? (
              <div className="banner-error">
                {plan.problems.map((p) => `${p.name}: ${p.problem}${p.short ? ` (${p.short} short)` : ""}`).join("; ")}.
                Make the missing prepared part first.
              </div>
            ) : null}
            {plan.unpriced.length ? (
              <div className="banner-warn">
                No price in the pool for {plan.unpriced.map((p) => p.name).join(", ")} on that
                date — they enter the lot at zero.
              </div>
            ) : null}
            <DataTable rows={plan.draws} columns={columns} rowKey={(d) => `${d.component_id}-${d.lot_adjustment_id ?? "p"}`} />
            <p className="muted">
              The new lot: <b>{plan.output.qty}</b> × {plan.output.name} worth{" "}
              <b>{usd(plan.output.value_usd)}</b> ({usd(plan.output.unit_cost_usd, 4)} each).
            </p>
          </>
        ) : null}

        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" onClick={() => onClose(false)}>Cancel</button>
          <button type="button" className="btn" disabled={busy || !qty} onClick={preview}>Preview</button>
          <button type="button" className="btn btn-primary" disabled={busy || !plan || blocked}
            onClick={commit}>Make it</button>
        </div>
      </div>
    </div>
  );
}
