/** The three stock corrections a prepared part takes (decision 0058 §7 and More
 *  Information), each a dry run before it writes:
 *
 *  - BANK: units of a prepared part that exist but that no transformation made — the
 *    found historical work. Zero value by default, because its component cost
 *    already sits in the closed batch that bought it.
 *  - TAKE STOCK: count the shelf; fewer than the books writes the difference
 *    off oldest lot first, more banks it at zero.
 *  - WRITE OFF: units of one lot that broke — the bench's "scrap one from the
 *    lot" — charged to a batch when one is named.
 */
import { useState } from "react";
import {
  bankStage,
  errorMessage,
  stocktakeStage,
  writeOffStage,
  type BankPlan,
  type RunInfo,
  type StageLot,
  type StocktakePlan,
  type WriteOffPlan,
} from "../../api";
import { usd } from "../../format";
import AutoTextarea from "../AutoTextarea";
import Field, { FieldGrid } from "../Field";
import NumberInput from "../NumberInput";
import { ErrorBanner, Spinner } from "../Ui";
import { today } from "./MakeDialog";
import { useModal } from "../modal";


/** The shared frame: fields, a preview line, Cancel / Preview / Apply.
 *  `applyLabel` and `canApply` let the preview decide what Apply says and
 *  whether it is offered ("Run on 28" when two units are skipped). */
export function DryRunDialog<P>({
  title, intro, fields, describe, run, onClose, applyLabel, canApply,
}: {
  title: string;
  intro: string;
  fields: React.ReactNode;
  describe: (plan: P) => React.ReactNode;
  run: (dry: boolean) => Promise<P>;
  onClose: (changed: boolean) => void;
  applyLabel?: (plan: P) => string;
  canApply?: (plan: P) => boolean;
}) {
  const modal = useModal(() => onClose(false));
  const [plan, setPlan] = useState<P | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async (dry: boolean) => {
    setBusy(true); setError(null);
    try {
      const p = await run(dry);
      if (dry) setPlan(p); else onClose(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">{title}</h2>
        <p className="muted dim">{intro}</p>
        {error ? <ErrorBanner message={error} /> : null}
        <div onChange={() => setPlan(null)}>{fields}</div>
        {plan ? <p className="muted">{describe(plan)}</p> : null}
        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" onClick={() => onClose(false)}>Cancel</button>
          <button type="button" className="btn" disabled={busy} onClick={() => go(true)}>Preview</button>
          <button type="button" className="btn btn-primary" disabled={busy || !plan || (canApply ? !canApply(plan) : false)}
            onClick={() => go(false)}>{plan && applyLabel ? applyLabel(plan) : "Apply"}</button>
        </div>
      </div>
    </div>
  );
}

export function BankDialog({ projectId, componentId, name, onClose }: {
  projectId: number; componentId: number; name: string; onClose: (changed: boolean) => void;
}) {
  const [qty, setQty] = useState<number | null>(null);
  const [unit, setUnit] = useState<number | null>(0);
  const [at, setAt] = useState(today());
  const [note, setNote] = useState("");
  return (
    <DryRunDialog<BankPlan>
      title={`Bank found units of ${name}`}
      intro="Units that exist but that no recorded transformation made. Enter them at zero value unless you know otherwise: their parts are already paid for by the batch that bought them, and closed books do not move. Say which batch that was."
      onClose={onClose}
      run={(dry) => bankStage(projectId, {
        component_id: componentId, qty: qty ?? 0, unit_cost_usd: unit ?? 0, at, note, dry_run: dry,
      })}
      describe={(p) => <>A new lot of <b>{p.qty}</b> × {p.name}, worth <b>{usd(p.value_usd)}</b>, dated {p.at}.</>}
      fields={
        <FieldGrid>
          <Field label="Units"><NumberInput className="text" value={qty} min={0} onChange={setQty} /></Field>
          <Field label="Value each (USD)"><NumberInput className="text" value={unit} min={0} onChange={setUnit} /></Field>
          <Field label="Counted on">
            <input className="text" type="date" value={at} onChange={(e) => setAt(e.target.value)} />
          </Field>
          <Field label="Where they came from" wide hint="required — which batch holds their cost, and how they were counted">
            <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

export function StocktakeDialog({ projectId, componentId, name, onBooks, onClose }: {
  projectId: number; componentId: number; name: string; onBooks: number;
  onClose: (changed: boolean) => void;
}) {
  const [counted, setCounted] = useState<number | null>(onBooks);
  const [at, setAt] = useState(today());
  const [note, setNote] = useState("");
  return (
    <DryRunDialog<StocktakePlan>
      title={`Take stock of ${name}`}
      intro={`The books say ${onBooks}. Count the shelf: fewer writes the difference off, oldest lot first; more banks it as a zero-value lot.`}
      onClose={onClose}
      run={(dry) => stocktakeStage(projectId, {
        component_id: componentId, counted: counted ?? 0, at, note, dry_run: dry,
      })}
      describe={(p) => (p.delta === 0
        ? <>The shelf matches the books — nothing to write.</>
        : p.delta < 0
          ? <>Writes off <b>{-p.delta}</b> (books {p.on_books}, counted {p.counted}).</>
          : <>Banks <b>{p.delta}</b> more at zero value (books {p.on_books}, counted {p.counted}).</>)}
      fields={
        <FieldGrid>
          <Field label="Counted"><NumberInput className="text" value={counted} min={0} onChange={setCounted} /></Field>
          <Field label="Counted on">
            <input className="text" type="date" value={at} onChange={(e) => setAt(e.target.value)} />
          </Field>
          <Field label="Who counted, and how" wide hint="required">
            <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

export function WriteOffDialog({ projectId, lot, name, runs, runId = null, onClose }: {
  projectId: number; lot: StageLot; name: string; runs: RunInfo[]; runId?: number | null;
  onClose: (changed: boolean) => void;
}) {
  const [qty, setQty] = useState<number | null>(1);
  const [charge, setCharge] = useState<number | null>(runId);
  const [at, setAt] = useState(today());
  const [note, setNote] = useState("");
  return (
    <DryRunDialog<WriteOffPlan>
      title={`Write off from lot A${lot.adjustment_id}`}
      intro={`${name}: ${lot.remaining} left in this lot at ${usd(lot.unit_cost_usd)} each. Name a batch to make it carry the loss; leave it empty and nobody is charged.`}
      onClose={onClose}
      run={(dry) => writeOffStage(projectId, {
        lot_adjustment_id: lot.adjustment_id, qty: qty ?? 0, at, charge_run_id: charge, note, dry_run: dry,
      })}
      describe={(p) => <>Writes off <b>{p.qty}</b>, worth <b>{usd(p.value_usd)}</b>.</>}
      fields={
        <FieldGrid>
          <Field label="Units"><NumberInput className="text" value={qty} min={0} onChange={setQty} /></Field>
          <Field label="Charge to batch">
            <select className="text" value={charge ?? ""}
              onChange={(e) => setCharge(e.target.value ? Number(e.target.value) : null)}>
              <option value="">nobody</option>
              {runs.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </Field>
          <Field label="On">
            <input className="text" type="date" value={at} onChange={(e) => setAt(e.target.value)} />
          </Field>
          <Field label="Why" wide hint="required">
            <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}
