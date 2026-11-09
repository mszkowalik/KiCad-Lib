/** Editing one planned date (decision 0107 item 5). A date is `fixed` on a day,
 *  or it comes `after` other dates of the plan plus a lag, and it may snap to a
 *  weekday. The same fields are used wherever a date is set — a new batch, a
 *  new lot, a new milestone — through `StepFields`, so there is one way to say
 *  "when" on every screen of the plan. */
import { useState } from "react";

import { updatePlanNode, type PlanFull, type PlanLagUnit, type PlanNode, type PlanNodeIn, type PlanParty, type PlanSource } from "../../api";
import Field, { FieldGrid } from "../Field";
import { StatChip } from "../FoldSection";
import { useModal } from "../modal";
import NumberInput from "../NumberInput";
import { dayNo, nodeLabel, refOptions, shortDay, WEEKDAY_NAMES, type Apply, type RefOption } from "./planUtil";

export interface StepValue {
  mode: "fixed" | "after";
  day: string;
  after: string[];
  lag: number;
  lag_unit: PlanLagUnit;
  snap_weekday: number | null;
}

export const LAG_UNITS: { value: PlanLagUnit; label: string }[] = [
  { value: "days", label: "days" },
  { value: "workdays", label: "working days" },
  { value: "weeks", label: "weeks" },
  { value: "months", label: "months" },
];

/** The references a date follows, as chips with a remove button, and a list to
 *  add one more. */
export function RefsPicker({ value, onChange, options }: {
  value: string[];
  onChange: (refs: string[]) => void;
  options: RefOption[];
}) {
  const label = new Map(options.map((o) => [o.ref, o]));
  const free = options.filter((o) => !value.includes(o.ref));
  return (
    <div className="plan-refs">
      {value.map((r) => {
        const o = label.get(r);
        return (
          <button key={r} type="button" className="stat-chip" title="Remove this reference"
            onClick={() => onChange(value.filter((x) => x !== r))}>
            <span>{o ? `${o.label}${o.day ? ` · ${shortDay(dayNo(o.day))}` : ""}` : r}</span>
            <b aria-hidden="true">×</b>
          </button>
        );
      })}
      <select className="text" value="" aria-label="Add a reference"
        onChange={(e) => e.target.value && onChange([...value, e.target.value])}>
        <option value="">{value.length ? "Add another date…" : "Choose the date it follows…"}</option>
        {free.map((o) => (
          <option key={o.ref} value={o.ref}>{o.label}{o.day ? ` · ${o.day}` : ""}</option>
        ))}
      </select>
    </div>
  );
}

/** "When": a fixed day, or after other dates plus a lag. */
export function StepFields({ value, onChange, options, snap = false, fixedLabel = "Day" }: {
  value: StepValue;
  onChange: (v: StepValue) => void;
  options: RefOption[];
  /** offer the weekday snap (deliveries) */
  snap?: boolean;
  fixedLabel?: string;
}) {
  const set = (p: Partial<StepValue>) => onChange({ ...value, ...p });
  return (
    <>
      <FieldGrid>
        <Field label="The date is">
          <select className="text" value={value.mode} onChange={(e) => set({ mode: e.target.value as StepValue["mode"] })}>
            <option value="fixed">fixed on a day</option>
            <option value="after">after other dates</option>
          </select>
        </Field>
        {value.mode === "fixed" ? (
          <Field label={fixedLabel}>
            <input className="text" type="date" value={value.day} onChange={(e) => set({ day: e.target.value })} />
          </Field>
        ) : (
          <>
            <Field label="Lag">
              <NumberInput className="text" value={value.lag} step={1} onChange={(v) => set({ lag: Math.round(v) })}
                onEmpty={() => set({ lag: 0 })} />
            </Field>
            <Field label="Unit">
              <select className="text" value={value.lag_unit} onChange={(e) => set({ lag_unit: e.target.value as PlanLagUnit })}>
                {LAG_UNITS.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
              </select>
            </Field>
          </>
        )}
        {snap ? (
          <Field label="Move to the next">
            <select className="text" value={value.snap_weekday ?? ""}
              onChange={(e) => set({ snap_weekday: e.target.value === "" ? null : Number(e.target.value) })}>
              <option value="">no weekday</option>
              {WEEKDAY_NAMES.map((w, i) => <option key={w} value={i}>{w}</option>)}
            </select>
          </Field>
        ) : null}
      </FieldGrid>
      <Field group label={value.mode === "after"
        ? "It follows the latest of these dates"
        : "It must not be before these dates (optional: a conflict shows otherwise)"}>
        <RefsPicker value={value.after} onChange={(after) => set({ after })} options={options} />
      </Field>
    </>
  );
}

/** A step is complete when a fixed one has a day and a following one has a
 *  reference. Returns what is missing, or "". */
export function stepProblem(v: StepValue): string {
  if (v.mode === "fixed" && !v.day) return "Choose the day.";
  if (v.mode === "after" && !v.after.length) return "Choose at least one date it follows.";
  return "";
}

export function stepOf(n: PlanNode): StepValue {
  return {
    mode: n.mode,
    day: n.day,
    after: n.after ?? [],
    lag: n.lag ?? 0,
    lag_unit: n.lag_unit ?? "days",
    snap_weekday: n.snap_weekday,
  };
}

export const SOURCES: { value: PlanSource; label: string }[] = [
  { value: "", label: "not stated" },
  { value: "estimate", label: "estimate" },
  { value: "measured", label: "measured" },
  { value: "confirmed", label: "confirmed" },
];

export const PARTIES: { value: PlanParty; label: string }[] = [
  { value: "ours", label: "ours" },
  { value: "customer", label: "the customer's" },
  { value: "supplier", label: "a supplier's" },
];

/** The dialog for one node. Every field the API takes is here; the date fields
 *  are `StepFields`. */
export default function NodeEditor({ full, node, title, onClose, apply }: {
  full: PlanFull;
  node: PlanNode;
  title?: string;
  onClose: () => void;
  apply: Apply;
}) {
  const modal = useModal(onClose);
  const [step, setStep] = useState<StepValue>(() => stepOf(node));
  const [label, setLabel] = useState(node.label);
  const [endDay, setEndDay] = useState(node.end_day);
  const [duration, setDuration] = useState<number | null>(node.duration_days);
  const [source, setSource] = useState<PlanSource>(node.source);
  const [sourceText, setSourceText] = useState(node.source_text);
  const [party, setParty] = useState<PlanParty>(node.party);
  const [doneOn, setDoneOn] = useState(node.done_on);
  const [amount, setAmount] = useState<number | null>(node.amount);
  const [busy, setBusy] = useState(false);
  const own = node.kind === "milestone" || node.kind === "closure";
  const problem = stepProblem(step) && !doneOn ? stepProblem(step) : "";
  const save = async () => {
    const body: PlanNodeIn = {
      mode: step.mode,
      day: step.day,
      after: step.after,
      lag: step.lag,
      lag_unit: step.lag_unit,
      snap_weekday: step.snap_weekday,
      source,
      source_text: sourceText,
      party,
      done_on: doneOn,
    };
    if (own) body.label = label.trim();
    if (node.kind === "closure") body.end_day = endDay;
    if (node.kind === "milestone") body.duration_days = duration;
    if (node.kind === "batch_order") body.amount = amount;
    setBusy(true);
    const ok = await apply(`the date "${nodeLabel(node)}"`, () => updatePlanNode(node.id, body));
    setBusy(false);
    if (ok) onClose();
  };
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">{title ?? `When: ${nodeLabel(node)}`}</h2>
        <p className="muted dim">
          A date that follows others moves when they move. A fixed date never moves by itself, and a
          date set as done is a fact.
        </p>
        {own ? (
          <FieldGrid>
            <Field label="Name" wide>
              <input className="text" value={label} onChange={(e) => setLabel(e.target.value)} />
            </Field>
          </FieldGrid>
        ) : null}
        <StepFields value={step} onChange={setStep} options={refOptions(full, node.id)}
          snap={node.kind === "delivery" || node.kind === "milestone"} />
        <FieldGrid>
          {node.kind === "closure" ? (
            <Field label="Closed until">
              <input className="text" type="date" value={endDay} onChange={(e) => setEndDay(e.target.value)} />
            </Field>
          ) : null}
          {node.kind === "milestone" ? (
            <Field label="Takes (days)" hint="Leave empty for a single day.">
              <NumberInput className="text" value={duration} onChange={(v) => setDuration(Math.round(v))}
                onEmpty={() => setDuration(null)} />
            </Field>
          ) : null}
          {node.kind === "batch_order" ? (
            <Field label={`PCBA cost estimate (${node.currency || "PLN"})`} hint="Counts as a purchase in the cash check.">
              <NumberInput className="text" value={amount} onChange={setAmount} onEmpty={() => setAmount(null)} />
            </Field>
          ) : null}
          <Field label="Whose date">
            <select className="text" value={party} onChange={(e) => setParty(e.target.value as PlanParty)}>
              {PARTIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </Field>
          <Field label="Source">
            <select className="text" value={source} onChange={(e) => setSource(e.target.value as PlanSource)}>
              {SOURCES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="Source text" hint="Who said so, and when.">
            <input className="text" value={sourceText} maxLength={300} onChange={(e) => setSourceText(e.target.value)} />
          </Field>
          <Field label="Done on" hint="The day it happened. Empty while it is still a plan.">
            <input className="text" type="date" value={doneOn} onChange={(e) => setDoneOn(e.target.value)} />
          </Field>
        </FieldGrid>
        <div className="btn-row modal-actions">
          {problem ? <StatChip tone="warn">{problem}</StatChip> : null}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !!problem || (own && !label.trim())}
            onClick={() => void save()}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
