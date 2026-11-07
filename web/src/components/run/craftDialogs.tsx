/** The dialogs of crafting a batch step by step (decision 0059). The page is
 *  `RunFloor`, with `ScanGroup` and `RunDevices`; these are what they open.
 *
 *  A crafted batch starts empty. "Receive boards" makes one unit (a twin) per
 *  board; every later step is a click on N units, with a dry run first.
 *
 *  - Before programming, units are taken from a STACK — "N from this pile",
 *    never one unit by its id, because nothing on an unprogrammed board says
 *    which one it is.
 *  - After programming, units are DEVICES, chosen by scanning their label or
 *    MAC, or by ticking them in the list. Each step records which of the two:
 *    a scan is an observation, a tick is a person's statement.
 *  - Programming and marking are done at their benches, which read the device.
 *    A device programmed with no stack selected is a GAP; a merge gives it a
 *    unit from a stack.
 *  - "Finished" is the last step, done here, and it refuses a device that
 *    misses a required step.
 *  - The board's assembly at the supplier is a step too (decision 0060). The
 *    person records it from the Board assembly card (decision 0072), with
 *    "Record assembly…": pre-filled from the JLC order, or filled in by hand
 *    for another assembly house. Receiving the boards does NOT record it, and
 *    neither does applying the JLC order. What arrives later stays out until
 *    "Add to assembly…" takes it in; "Undo assembly…" reverses the newest
 *    write through the ledger. Any other invoice position of the batch can be
 *    linked to the step click it paid for; what no step claims stays in the
 *    origin batch cost.
 */
import { useState } from "react";
import {
  ApiError,
  craftCosts,
  craftFinish,
  craftFound,
  craftMerge,
  craftReceive,
  craftRelink,
  craftReopen,
  craftScrap,
  craftStep,
  craftSwap,
  errorMessage,
  getProjectProcess,
  getRuns,
  linkDevicesToRun,
  rebatchDevices,
  REBUILD_ADVANCED_KEYS,
  rebuildRun,
  repinRun,
  reverseWriteBatch,
  undoRebuildRun,
  type AssemblyDraft,
  type CraftStack,
  type CraftView,
  type ProcessVersionRow,
  type RebatchPlan,
  type RebuildPlan,
  type RebuildUndoPlan,
  type RepinPlan,
  type RunInfo,
  type StepPlan,
} from "../../api";
import { plural, pln, today } from "../../format";
import { parseScanSheet } from "../../scanSheet";
import { Link } from "react-router-dom";
import { useClicks } from "./useClicks";
import type { Craft } from "./useCraft";
import AutoTextarea from "../AutoTextarea";
import AssemblyDialog, { lineKind } from "./AssemblyDialog";
import DataTable from "../DataTable";
import { useDialog, type DialogApi } from "../Dialog";
import Field, { CheckField, FieldGrid } from "../Field";
import FoldSection from "../FoldSection";
import InfoTip from "../InfoTip";
import NumberInput from "../NumberInput";
import { DryRunDialog } from "../process/StageDialogs";
import { RebuildPlanView, RebuildUndoView, rebuildSummary } from "./RebuildPlan";
import { SerialsField } from "../ScanList";
import { ErrorBanner, Spinner } from "../Ui";
import { useLoad } from "../useLoad";

export type Target = { kind: "stack"; stack: CraftStack } | { kind: "devices"; ids: number[]; chosen: "scanned" | "list" };

/** A stack in words: the steps its units have done, and the lots they used. */
export function stackText(s: CraftStack, label: (k: string) => string): string {
  const done = s.done.map(label).join(" + ");
  return s.lots.length ? `${done} (lots ${s.lots.join(", ")})` : done;
}

/** Bench steps a person may STATE on named devices, with the reason (decision 0074). */
export const STATABLE = ["test", "mark_laser", "label"];

/** What a step is called on this batch: its label, or its key when it has none. */
export function stepLabelOf(view: CraftView | null): (key: string) => string {
  return (key) => view?.graph.steps.find((s) => s.key === key)?.label || key;
}

/** Devices the server refused, one sentence each. */
function refusedText(refused: { unit: string; why: string[] }[]): string {
  return refused.map((r) => `${r.unit} — ${r.why.join(", ")}`).join("; ");
}

function StepDialog({ run, view, target, stepKey: initialStep, onClose }: {
  run: RunInfo; view: CraftView; target: Target;
  /** the step a board field asked for */
  stepKey?: string;
  onClose: (changed: boolean) => void;
}) {
  // On named devices a person may also STATE a test, mark or label step that
  // no bench run recorded, with the reason (decision 0074).
  const steps = view.graph.steps.filter((s) => s.kind === "step"
    || (target.kind === "devices" && STATABLE.includes(s.kind ?? "")));
  const allowed = target.kind === "stack" ? new Set(target.stack.can ?? []) : null;
  const choices = steps.filter((s) => !allowed || allowed.has(s.key));
  const [stepKey, setStepKey] = useState(
    choices.some((s) => s.key === initialStep) ? (initialStep as string) : choices[0]?.key ?? "");
  const [qty, setQty] = useState<number | null>(target.kind === "stack" ? target.stack.count : null);
  const [madeAt, setMadeAt] = useState(today());
  const [note, setNote] = useState("");
  const [lots, setLots] = useState<Record<string, number>>({});
  const [stated, setStated] = useState("");
  const step = steps.find((s) => s.key === stepKey);
  const isStated = STATABLE.includes(step?.kind ?? "");
  const preparedInputs = (step?.inputs ?? []).filter((i) => view.parts[String(i.component_id)]?.internal);
  // Named devices are judged one by one: a device that already has the step,
  // or lacks what it needs, is skipped and named, and the rest take it. A
  // stack is one pile, so it is still all or nothing.
  const devices = target.kind === "devices";
  const body = (dry: boolean) => ({
    step_key: stepKey, made_at: madeAt, note, dry_run: dry,
    lots: Object.keys(lots).length ? lots : null,
    ...(isStated ? { stated } : {}),
    ...(target.kind === "stack"
      ? { stack: target.stack.stack, qty: qty ?? 0 }
      : { device_ids: target.ids, chosen: target.chosen, skip_refused: true }),
  });
  return (
    <DryRunDialog<StepPlan>
      title="Run a step"
      intro={target.kind === "stack"
        ? `On units from the stack “${stackText(target.stack, stepLabelOf(view))}”.`
        : `On ${target.ids.length} device(s), ${target.chosen === "scanned" ? "scanned" : "picked from the list"}.`}
      onClose={onClose}
      run={(dry) => craftStep(run.id, body(dry))}
      applyLabel={(p) => (devices && p.refused.length && p.units ? `Run on ${p.units}` : "Apply")}
      canApply={(p) => !devices || p.units > 0}
      describe={(p) => (
        <>
          {devices && p.refused.length && p.units ? (
            <span className="banner-warn">
              {p.refused.length} of {p.selected} skipped: {refusedText(p.refused)}
            </span>
          ) : devices && p.refused.length ? (
            <span className="banner-error">
              None of the {p.selected} device(s) can take this step: {refusedText(p.refused)}
            </span>
          ) : p.refused.length ? (
            <span className="banner-error">Refused: {refusedText(p.refused)}</span>
          ) : null}
          {p.shortages.length ? (
            <span className="banner-error">Not in stock: {p.shortages.map((s) => `${s.label} (${s.short} short)`).join(", ")}</span>
          ) : null}
          {p.problems.length ? (
            <span className="banner-error">{p.problems.map((x) => `${x.name}: ${x.problem}`).join("; ")}</span>
          ) : null}
          {devices && !p.units ? null : (
            <>
              {p.units}{devices && p.refused.length ? ` of ${p.selected}` : ""} unit(s) take {p.draws.length ? p.draws.map((d) => `${d.qty} × ${d.name}${d.lot_adjustment_id ? ` (lot A${d.lot_adjustment_id})` : ""}`).join(", ") : "no parts"}
              {p.draws.length ? <> — {pln(p.value_usd, view.pln_per_usd)}, {pln(p.per_unit_usd, view.pln_per_usd, 4)} per unit, charged to {run.label}.</> : "."}
            </>
          )}
        </>
      )}
      fields={
        <FieldGrid>
          <Field label="Step">
            <select className="text" value={stepKey} onChange={(e) => { setStepKey(e.target.value); setLots({}); }}>
              {choices.map((s) => <option key={s.key} value={s.key}>{s.label || s.key}{s.required ? "" : " (optional)"}
                {STATABLE.includes(s.kind ?? "") ? " — state it" : ""}</option>)}
            </select>
          </Field>
          {isStated ? (
            <Field label="Why no bench recorded it" wide hint="required — the step is saved as your statement">
              <AutoTextarea className="text" value={stated} onChange={(e) => setStated(e.target.value)} />
            </Field>
          ) : null}
          {target.kind === "stack" ? (
            <Field label="Units" hint={`of ${target.stack.count} in the stack`}>
              <NumberInput className="text" value={qty} min={1} max={target.stack.count} onChange={setQty} />
            </Field>
          ) : null}
          <Field label="Done on">
            <input className="text" type="date" value={madeAt} onChange={(e) => setMadeAt(e.target.value)} />
          </Field>
          {preparedInputs.map((i) => (
            <Field key={i.component_id} label={`Lot of ${view.parts[String(i.component_id)]?.name}`}
              hint="one lot per click, so the units stay one pile">
              <NumberInput className="text" value={lots[String(i.component_id)] ?? null} min={1}
                placeholder="oldest lot that holds enough"
                onChange={(v) => setLots({ ...lots, [String(i.component_id)]: v })} />
            </Field>
          ))}
          <Field label="Note" wide>
            <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

/** Link invoice positions to the step clicks they paid for (decisions 0060,
 *  0061). One invoice can pay for several steps — the final assembler's covers
 *  programming, the enclosure, the laser mark and the label — and the units of
 *  all the clicks ticked share it. A scrap is no step a cost can pay for. */
function LinkDialog({ run, view, lineIds, what, onClose }: {
  run: RunInfo; view: CraftView; lineIds: number[]; what: string;
  onClose: (c: boolean) => void;
}) {
  // The single clicks start with the newest page and load older ones on
  // request, so a click of any age can be ticked.
  const list = useClicks(run.id, view);
  const options = list.clicks.filter((c) => c.qty > 0 && c.kind !== "scrap");
  const [ticked, setTicked] = useState<number[]>([]);
  const [wholeSteps, setWholeSteps] = useState<string[]>([]);
  const toggle = (id: number, on: boolean) =>
    setTicked((t) => (on ? [...t, id] : t.filter((x) => x !== id)));
  // A whole step goes to the server by its key, which resolves EVERY click of
  // it — programming is one click per device — and also covers the clicks
  // recorded after the link (decision 0074), so a step with no click yet is
  // offered too.
  const steps: [string, string][] = view.graph.steps.map((s) => [s.key, s.label || s.key]);
  const tickStep = (step: string, on: boolean) =>
    setWholeSteps((w) => (on ? [...new Set([...w, step])] : w.filter((x) => x !== step)));
  return (
    <DryRunDialog<{ lines: { line_id: number; label: string }[]; refused: { label: string; why: string }[] }>
      title="Link to steps"
      intro={`“${what}” paid for these step clicks. Their units share it equally; the money stays charged to ${run.label}.`}
      onClose={onClose}
      run={(dry) => craftCosts(run.id, { step_run_ids: ticked, step_keys: wholeSteps, line_ids: lineIds,
                                         dry_run: dry })}
      describe={(p) => (p.refused.length
        ? <span className="banner-error">Refused: {p.refused.map((r) => `${r.label} — ${r.why}`).join("; ")}</span>
        : <>{p.lines.length} position(s) will be linked to {wholeSteps.length} whole step(s)
            {ticked.length ? ` and ${ticked.length} single click(s)` : ""}.</>)}
      fields={
        <>
          <Field group label="Whole steps" wide hint="also every click of the step recorded later">
            <div className="btn-row">
              {steps.map(([step, label]) => (
                <CheckField key={step} checked={wholeSteps.includes(step)}
                  onChange={(v) => tickStep(step, v)}>{label}</CheckField>
              ))}
            </div>
          </Field>
          <Field group label="Or single clicks" wide
            hint={list.clicks.length < list.total
              ? `the newest ${list.clicks.length} of ${list.total} clicks` : undefined}>
            <div>
              {options.map((c) => (
                <CheckField key={c.id} checked={ticked.includes(c.id)} onChange={(v) => toggle(c.id, v)}>
                  {c.made_at} · {c.label} · {c.qty} unit(s)
                </CheckField>
              ))}
              {list.error ? <ErrorBanner message={list.error} /> : null}
              {list.clicks.length < list.total ? (
                <button type="button" className="btn btn-sm" disabled={list.loading}
                  onClick={() => list.more(200)}>{list.loading ? "Loading…" : "Load 200 older clicks"}</button>
              ) : null}
            </div>
          </Field>
        </>
      }
    />
  );
}

/** Receive the boards: the person's count makes the twins (decision 0072).
 *  Pre-filled with JLC's board count when the batch has a JLC order that
 *  states one, else with the batch's planned quantity — and the field says
 *  which, because the number is a suggestion to check against the box. */
function ReceiveDialog({ run, boardsJlc, orders, onClose }: {
  run: RunInfo; boardsJlc: number | null; orders: string[]; onClose: (c: boolean) => void;
}) {
  const fromJlc = typeof boardsJlc === "number";
  const [qty, setQty] = useState<number | null>(fromJlc ? boardsJlc : (run.qty || null));
  const [madeAt, setMadeAt] = useState(today());
  return (
    <DryRunDialog<{ qty: number; received_before: number; ordered: number; over_order: boolean }>
      title="Receive boards"
      intro="One unit per board you count. Receiving does not record the assembly. Record it on the Board assembly card after this."
      onClose={onClose}
      run={(dry) => craftReceive(run.id, { qty: qty ?? 0, made_at: madeAt, dry_run: dry })}
      describe={(p) => (
        <>
          {p.qty} unit(s); {p.received_before} received before, {p.ordered} ordered.
          {p.over_order ? <span className="banner-warn"> That is more than the order.</span> : null}
        </>
      )}
      fields={
        <FieldGrid>
          <Field label="Boards"
            hint={fromJlc
              ? `JLC's board count for ${orders.join(", ") || "the linked order"}`
              : run.qty ? "the batch's planned quantity" : undefined}>
            <NumberInput className="text" value={qty} min={1} onChange={setQty} />
          </Field>
          <Field label="Received on">
            <input className="text" type="date" value={madeAt} onChange={(e) => setMadeAt(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

/** A refusal in words. The ledger's 409 carries its reasons beside the
 *  sentence (`blockers`, `blocking_batches`), so the sentence alone says only
 *  "cannot reverse this batch". */
export function refusalText(err: unknown): string {
  const msg = errorMessage(err);
  if (!(err instanceof ApiError) || !err.detail || typeof err.detail !== "object") return msg;
  const d = err.detail as { blockers?: unknown; blocking_batches?: unknown };
  const blockers = Array.isArray(d.blockers) ? d.blockers.map(String) : [];
  const later = Array.isArray(d.blocking_batches) ? d.blocking_batches.map(String) : [];
  return [
    msg.endsWith(".") ? msg : `${msg}.`,
    ...blockers.map((b) => (b.endsWith(".") ? b : `${b}.`)),
    later.length ? `Undo write batch ${later.join(", ")} first.` : "",
  ].filter(Boolean).join(" ");
}

/** Undo one ledger write: the dry run, then the person's answer, then the write.
 *  A refusal at either call is an alert in words, and the answer is whether the
 *  write was undone, so the caller knows to read the page again. */
export async function undoWrite(dialog: DialogApi, batchId: number, title: string,
  question: (would: { delete: number; restore: number; reinsert: number }) => string): Promise<boolean> {
  try {
    const plan = await reverseWriteBatch(batchId, true);
    if (!(await dialog.confirm(question(plan.would), { title, confirmLabel: "Undo", tone: "danger" }))) return false;
    await reverseWriteBatch(batchId, false);
    return true;
  } catch (err) {
    await dialog.alert(refusalText(err), { title: "Undo refused" });
    return false;
  }
}

/** What waits outside the assembly step, in words — "" when nothing does. */
function waitingText(d: AssemblyDraft): string {
  const inStep = new Set((d.recorded?.lines ?? []).map((l) => l.line_id));
  const twins = d.status === "recorded" ? (d.header.twins_not_in_step ?? 0)
    : d.status === "open" ? (d.header.twins ?? 0) : 0;
  const broken = new Set(d.parts_supplied.map((r) => r.parent_line_id));
  // A parts total with no breakdown can only go in whole, so it counts as a
  // position; one with a breakdown counts as its rows.
  const positions = d.lines.filter((l) => lineKind(l) === "position"
    || (lineKind(l) === "parts_lump" && !broken.has(l.line_id))).length;
  const supplied = d.lines.filter((l) => lineKind(l) === "supplied_part").length
    + d.parts_supplied.filter((r) => r.source !== "rounding" && !inStep.has(r.parent_line_id)).length;
  return [
    twins ? plural(twins, "twin") : "",
    positions ? plural(positions, "position") : "",
    d.parts_from_stock.length ? `${plural(d.parts_from_stock.length, "part")} from our stock` : "",
    supplied ? `${plural(supplied, "part")} the assembler supplied` : "",
    d.replacements.length ? plural(d.replacements.length, "replacement") : "",
  ].filter(Boolean).join(", ");
}

/** The Board assembly card: the step's state, what waits outside it, and the
 *  three controls — record it, add to it, undo the newest write. */
export function AssemblyCard({ run, draft, error, onOpen, onChanged }: {
  run: RunInfo; draft: AssemblyDraft | null; error: string | null;
  onOpen: () => void; onChanged: () => void;
}) {
  const dialog = useDialog();
  const [busy, setBusy] = useState(false);
  if (error) {
    return (
      <div className="card pad">
        <h2 className="card-title">Board assembly</h2>
        <ErrorBanner message={error} />
      </div>
    );
  }
  if (!draft) {
    return (
      <div className="card pad">
        <h2 className="card-title">Board assembly</h2>
        <Spinner />
      </div>
    );
  }
  const rec = draft.recorded;
  const waiting = waitingText(draft);
  const newest = rec?.batch_ids[0];
  // `recorded.lines` carry no `kind`. A part the assembler supplied is a
  // `pcba:parts` line (a child of a split total, or a total linked whole);
  // every other linked line is a position.
  const suppliedLines = (rec?.lines ?? []).filter((l) => l.plan_key === "pcba:parts").length;

  const undo = async () => {
    if (!newest) return;
    setBusy(true);
    try {
      const undone = await undoWrite(dialog, newest, "Undo assembly", (would) =>
        `Undo the newest assembly write of ${run.label} (write batch ${newest})? It deletes ` +
        `${would.delete}, restores ${would.restore} and re-inserts ${would.reinsert} ` +
        "row(s), so everything that write put in the step comes out again." +
        (rec && rec.batch_ids.length > 1
          ? ` The step keeps what the ${plural(rec.batch_ids.length - 1, "earlier write")} put in.` : ""));
      if (undone) onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card pad">
      <h2 className="card-title">Board assembly</h2>
      {draft.closed ? <p className="banner-warn">{run.label} is closed. The assembly step cannot change.</p> : null}
      {draft.status === "no_assembly_step" ? (
        <p className="muted dim">The process of this batch has no assembly step, so there is nothing to record.</p>
      ) : draft.status === "recorded" && rec ? (
        <>
          <p className="muted dim">
            {rec.chosen === "rebuilt" ? "Rebuilt from the batch's records, dated" : "Recorded on"} {rec.made_at}
            {rec.assembler ? ` by ${rec.assembler}` : ""}
            {rec.reference ? `, reference ${rec.reference}` : ""}: {plural(rec.units, "unit")},{" "}
            {plural(rec.lines.length - suppliedLines, "position")},{" "}
            {plural(rec.draws.length, "part")} from our stock,{" "}
            {plural(suppliedLines, "part")} the assembler supplied,{" "}
            {plural(rec.replacements.length, "replacement")}.
          </p>
          <p className="muted dim">
            {waiting ? `Not in the assembly step: ${waiting}.` : "Nothing waits outside the assembly step."}
          </p>
        </>
      ) : (
        <>
          <p className="muted dim">
            Not recorded yet.{draft.status === "no_twins" ? " Receive the boards first." : ""}
            {(draft.header.orders ?? []).length
              ? ` The JLC order ${(draft.header.orders ?? []).join(", ")} pre-fills it.`
              : " No JLC order is linked, so you fill it in by hand."}
          </p>
          {waiting ? <p className="muted dim">Ready to go in: {waiting}.</p> : null}
        </>
      )}
      {draft.status === "open" || draft.status === "recorded" ? (
        <div className="btn-row">
          {draft.status === "open" ? (
            <button type="button" className="btn btn-primary" onClick={onOpen}>Record assembly…</button>
          ) : (
            <>
              <button type="button" className="btn" disabled={!waiting} onClick={onOpen}
                title={waiting ? undefined : "Nothing waits outside the assembly step."}>
                Add to assembly…
              </button>
              <button type="button" className="btn btn-danger" disabled={busy || !newest} onClick={undo}
                title={newest ? undefined : "No write of this step is left to undo in the ledger."}>
                Undo assembly…
              </button>
            </>
          )}
          {busy ? <Spinner /> : null}
        </div>
      ) : null}
    </div>
  );
}

function FoundDialog({ run, view, runs, onClose }: {
  run: RunInfo; view: CraftView; runs: RunInfo[]; onClose: (c: boolean) => void;
}) {
  const [qty, setQty] = useState<number | null>(null);
  const [done, setDone] = useState<string[]>([]);
  const [origin, setOrigin] = useState<number>(run.id);
  const [note, setNote] = useState("");
  const steps = view.graph.steps.filter((s) => s.kind === "step" || s.kind === "mark_laser" || s.kind === "label");
  return (
    <DryRunDialog<{ units: number; done: string[] }>
      title="Enter found units"
      intro="Units that exist but have no record — found at a stock count. They enter at zero value: their cost already sits in the books of the batch they came from."
      onClose={onClose}
      run={(dry) => craftFound(run.id, { qty: qty ?? 0, done, origin_run_id: origin, note, dry_run: dry })}
      describe={(p) => <>{p.units} unit(s) enter with: {p.done.join(", ")}.</>}
      fields={
        <FieldGrid>
          <Field label="Units"><NumberInput className="text" value={qty} min={1} onChange={setQty} /></Field>
          <Field label="Came from batch" hint="whose books hold their cost">
            <select className="text" value={origin} onChange={(e) => setOrigin(Number(e.target.value))}>
              {runs.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </Field>
          <Field group label="Already done" wide>
            <div className="btn-row">
              {steps.map((s) => (
                <CheckField key={s.key} checked={done.includes(s.key)}
                  onChange={(v) => setDone(v ? [...done, s.key] : done.filter((k) => k !== s.key))}>
                  {s.label || s.key}
                </CheckField>
              ))}
            </div>
          </Field>
          <Field label="Where they were found" wide hint="required">
            <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

/** Move the batch to another published version of its process (decision
 *  0074): a version published with an error, or the one that really describes
 *  how its devices were made. The clicks keep the version they ran under. */
function RepinDialog({ run, view, onClose }: { run: RunInfo; view: CraftView; onClose: (c: boolean) => void }) {
  const versions = useLoad(
    (signal) => getProjectProcess(run.project_id, null, signal)
      .then((d) => d.versions.filter((v) => v.status === "published" && v.id !== view.process_version_id)),
    [run.project_id, view.process_version_id],
    { keep: true },
  ).data ?? [];
  const [target, setTarget] = useState<number | null>(null);
  return (
    <DryRunDialog<RepinPlan>
      title="Change process version"
      intro={`${run.label} runs process v${view.version_no}. A twin that has done a step the new version lacks refuses the change. To go back, change it again.`}
      onClose={onClose}
      run={(dry) => repinRun(run.id, target ?? 0, dry)}
      describe={(p) => (
        <>
          v{p.from_version} → v{p.to_version}, {p.twins} twin(s).
          {p.added_steps.length ? <> New steps: {p.added_steps.join(", ")}.</> : null}
          {p.removed_steps.length ? <> Steps no twin has done, dropped: {p.removed_steps.join(", ")}.</> : null}
        </>
      )}
      fields={
        <FieldGrid>
          <Field label="Version" wide>
            <select className="text" value={target ?? ""} onChange={(e) => setTarget(Number(e.target.value) || null)}>
              <option value="">— choose —</option>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>v{v.version_no} · {v.comment.slice(0, 80)}</option>
              ))}
            </select>
          </Field>
        </FieldGrid>
      }
    />
  );
}

function ReopenDialog({ run, ids, chosen, onClose }: {
  run: RunInfo; ids: number[]; chosen: "scanned" | "list"; onClose: (c: boolean) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <DryRunDialog<{ units: number; refused: { unit: string; why: string[] }[] }>
      title="Reopen for rework"
      intro={`${ids.length} finished device(s) go back into work. They can take steps again, and ship only after a new finish.`}
      onClose={onClose}
      run={(dry) => craftReopen(run.id, { device_ids: ids, chosen, reason, dry_run: dry })}
      describe={(p) => (p.refused.length
        ? <span className="banner-error">Refused: {refusedText(p.refused)}</span>
        : <>{p.units} device(s) will be reopened.</>)}
      fields={
        <FieldGrid>
          <Field label="Why" wide hint="required">
            <AutoTextarea className="text" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

function SwapDialog({ run, view, id, label, onClose }: {
  run: RunInfo; view: CraftView; id: number; label: (k: string) => string; onClose: (c: boolean) => void;
}) {
  const dev = view.devices.find((d) => d.device_id === id);
  const [stack, setStack] = useState(view.bench_stacks[0]?.stack ?? "");
  return (
    <DryRunDialog<{ from_twin: number; to_twin: number; back_to_stack: string }>
      title="Swap twin"
      intro={`${dev?.serial || dev?.mac || id} takes a board of the stack you choose, and the board it was named with goes back to its own stack, unnamed. Its programming step moves with it.`}
      onClose={onClose}
      run={(dry) => craftSwap(run.id, { device_ids: [id], stack, dry_run: dry })}
      describe={(p) => <>Twin #{p.from_twin} goes back to {p.back_to_stack}; the device takes twin #{p.to_twin}.</>}
      fields={
        <FieldGrid>
          <Field label="The right stack" wide>
            <select className="text" value={stack} onChange={(e) => setStack(e.target.value)}>
              {view.bench_stacks.map((s) => <option key={s.stack} value={s.stack}>{stackText(s, label)} · {s.count}</option>)}
            </select>
          </Field>
        </FieldGrid>
      }
    />
  );
}

function RelinkDialog({ run, view, id, onClose }: {
  run: RunInfo; view: CraftView; id: number; onClose: (c: boolean) => void;
}) {
  const dev = view.devices.find((d) => d.device_id === id);
  const [runId, setRunId] = useState<number | null>(null);
  return (
    <DryRunDialog<{ from_device: string | null; to_device: string; steps: string[] }>
      title="Relink run"
      intro={`Move a bench run filed against another device to ${dev?.serial || dev?.mac || id}, with the steps it recorded. A run that named its device is moved with "Swap twin" instead.`}
      onClose={onClose}
      run={(dry) => craftRelink(run.id, { programming_run_id: runId ?? 0, device_ids: [id], dry_run: dry })}
      describe={(p) => <>Run moves from {p.from_device ?? "no device"} to {p.to_device}
        {p.steps.length ? `, with ${p.steps.join(", ")}` : ", with no step"}.</>}
      fields={
        <FieldGrid>
          <Field label="Programming run" hint="its number, from the device page or the bench history">
            <NumberInput className="text" value={runId} min={1} onChange={setRunId} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

function ScrapDialog({ run, target, onClose }: { run: RunInfo; target: Target; onClose: (c: boolean) => void }) {
  const [qty, setQty] = useState<number | null>(1);
  const [reason, setReason] = useState("");
  return (
    <DryRunDialog<{ units: number; disposed?: number; refused?: { unit: string; why: string[] }[] }>
      title="Scrap units"
      intro="Their price is carried by the other units of the batch they came from, until that batch is closed."
      onClose={onClose}
      run={(dry) => craftScrap(run.id, {
        reason, dry_run: dry,
        ...(target.kind === "stack" ? { stack: target.stack.stack, qty: qty ?? 0 } : { device_ids: target.ids, chosen: target.chosen }),
      })}
      describe={(p) => (p.refused?.length
        ? <span className="banner-error">Refused: {refusedText(p.refused)}</span>
        : <>{p.units} unit(s) will be scrapped{p.disposed ? `, and ${p.disposed} named device(s) recorded as disposed of` : ""}.</>)}
      fields={
        <FieldGrid>
          {target.kind === "stack" ? (
            <Field label="Units" hint={`of ${target.stack.count}`}>
              <NumberInput className="text" value={qty} min={1} max={target.stack.count} onChange={setQty} />
            </Field>
          ) : null}
          <Field label="Why" wide hint="required">
            <AutoTextarea className="text" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

function MergeDialog({ run, view, ids, label, onClose }: {
  run: RunInfo; view: CraftView; ids: number[]; label: (k: string) => string; onClose: (c: boolean) => void;
}) {
  // The bench's stack only while it still holds units: a used-up one is in no
  // option, and sending it would merge from nothing.
  const ready = view.bench_stacks.some((s) => s.stack === view.bench_stack);
  const [stack, setStack] = useState((ready ? view.bench_stack : null) ?? view.bench_stacks[0]?.stack ?? "");
  return (
    <DryRunDialog<{ units: number; stack: string }>
      title="Merge gaps"
      intro={`${ids.length} programmed device(s) take a unit from the stack they came from.`}
      onClose={onClose}
      run={(dry) => craftMerge(run.id, { stack, device_ids: ids, chosen: "list", dry_run: dry })}
      describe={(p) => <>{p.units} device(s) take units from the stack.</>}
      fields={
        <Field label="Stack they came from">
          <select className="text" value={stack} onChange={(e) => setStack(e.target.value)}>
            {view.bench_stacks.map((s) => (
              <option key={s.stack} value={s.stack}>{s.run_label}: {stackText(s, label)} — {s.count}</option>
            ))}
          </select>
        </Field>
      }
    />
  );
}

/** Link devices that no batch has claimed: a device programmed before batches
 *  recorded their devices has no `produced` event. Each gets one here. */
export function LinkProducedDialog({ run, onClose }: { run: RunInfo; onClose: (c: boolean) => void }) {
  const [text, setText] = useState("");
  const serials = parseScanSheet(text);
  return (
    <DryRunDialog<{ linked: number; skipped: { id: number; reason: string }[] }>
      title="Link devices no batch has claimed"
      intro={`Each device gets one "produced" event on ${run.label}. A device that already has one is skipped: move it instead.`}
      onClose={onClose}
      run={(dry) => linkDevicesToRun(run.id, { serials, dry_run: dry })}
      canApply={(p) => p.linked > 0}
      applyLabel={(p) => `Link ${p.linked}`}
      describe={(p) => (
        <>
          {p.linked} device(s) are linked, {p.skipped.length} skipped.
          {p.skipped.length ? <span className="muted dim"> {p.skipped.map((x) => `${x.id}: ${x.reason}`).join("; ")}</span> : null}
        </>
      )}
      fields={
        <SerialsField value={text} onChange={setText} />
      }
    />
  );
}

/** Move devices filed against the wrong batch into this one (decision 0029): a
 *  bench that had the wrong batch selected. The devices are named by scanned
 *  serial, so a paste of a scanner's CSV works as it is. */
export function RebatchDialog({ run, onClose }: { run: RunInfo; onClose: (c: boolean) => void }) {
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const runs = useLoad((signal) => getRuns(run.project_id, signal), [run.project_id], { keep: true }).data ?? [];
  const serials = parseScanSheet(text);
  const batchName = (id: number | null) => runs.find((r) => r.id === id)?.label ?? (id ? `batch ${id}` : "no batch");
  return (
    <DryRunDialog<RebatchPlan>
      wide
      title="Move devices into this batch"
      intro={`Use this when a bench had the wrong batch selected. Each device and its programming attempts on the old batch move to ${run.label}. A device whose twin was rebuilt is refused. Undo that rebuild first.`}
      onClose={onClose}
      run={(dry) => rebatchDevices(run.id, { serials, note, dry_run: dry })}
      canApply={(p) => p.moved.length > 0}
      applyLabel={(p) => `Move ${p.moved.length}`}
      describe={(p) => <>{p.moved.length} device(s) move, {p.skipped.length} stay where they are.</>}
      detail={(p) => (
        <>
          {p.skipped.length ? (
            <FoldSection bare title="Stay where they are" count={p.skipped.length}>
              <DataTable rows={p.skipped} rowKey={(r) => r.device_id}
                columns={[
                  { key: "device", label: "Device", width: 15, className: "mono", get: (r) => r.serial || String(r.device_id) },
                  { key: "why", label: "Why", width: 85, get: (r) => r.reason, title: (r) => r.reason },
                ]} />
            </FoldSection>
          ) : null}
          {p.moved.length ? (
            <FoldSection bare title="Move" count={p.moved.length}>
              <DataTable rows={p.moved} rowKey={(r) => r.device_id}
                columns={[
                  { key: "device", label: "Device", width: 30, className: "mono", get: (r) => r.serial },
                  { key: "from", label: "From", width: 50, get: (r) => batchName(r.from_run_id) },
                  { key: "attempts", label: "Attempts", width: 20, numeric: true, get: (r) => r.attempts },
                ]} />
            </FoldSection>
          ) : null}
        </>
      )}
      fields={
        <FieldGrid>
          <SerialsField value={text} onChange={setText} />
          <Field label="Note" wide hint="Goes on each device's history, after where it came from.">
            <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
      }
    />
  );
}

/** The advanced box of a rebuild: one JSON object with the inputs that have no
 *  plain field. A key the server does not know would be ignored in silence, and a
 *  misspelt `settle` then reads as a refusal for no reason, so it is refused here. */
function parseAdvanced(text: string): { value: Record<string, unknown>; error: string } {
  const t = text.trim();
  if (!t) return { value: {}, error: "" };
  let v: unknown;
  try {
    v = JSON.parse(t);
  } catch (err) {
    return { value: {}, error: `This is not valid JSON: ${errorMessage(err)}` };
  }
  if (typeof v !== "object" || v === null || Array.isArray(v)) {
    return { value: {}, error: "Write one JSON object, in braces." };
  }
  const known: readonly string[] = REBUILD_ADVANCED_KEYS;
  const bad = Object.keys(v).filter((k) => !known.includes(k));
  if (bad.length) {
    return { value: {}, error: `Unknown input: ${bad.join(", ")}. The inputs are ${known.join(", ")}.` };
  }
  return { value: v as Record<string, unknown>, error: "" };
}

/** Give a batch made before twins its twins from its records, or with `append`
 *  the devices that joined it since (decisions 0060, 0075). Nothing here is
 *  written before the dry run was read: it is the review. */
export function RebuildDialog({ run, onClose }: { run: RunInfo; onClose: (c: boolean) => void }) {
  const pinned = run.process_version_id ?? null;
  const [versionId, setVersionId] = useState<number | null>(pinned);
  const [append, setAppend] = useState(pinned !== null);
  const [advanced, setAdvanced] = useState("");
  const { data: versions } = useLoad<ProcessVersionRow[]>(
    (signal) =>
      getProjectProcess(run.project_id, null, signal)
        .then((d) => {
          const published = d.versions.filter((v) => v.status === "published");
          setVersionId((was) => was ?? d.current_version_id ?? published[0]?.id ?? null);
          return published;
        })
        .catch(() => []),
    [run.project_id],
    { keep: true },
  );
  const parsed = parseAdvanced(advanced);
  return (
    <DryRunDialog<RebuildPlan>
      wide
      title="Rebuild twins"
      intro={`This gives ${run.label} one twin per device it produced, and records the steps its records prove. Do two things first: link the old bench runs on the project's Process tab, and move devices between batches. A rebuild misses a run that is not linked, and it refuses a later move. A write is one journal batch, and Undo rebuild takes it back.`}
      onClose={onClose}
      run={(dry) => {
        if (parsed.error) return Promise.reject(new Error(parsed.error));
        return rebuildRun(run.id, {
          ...parsed.value,
          ...(append ? {} : { version_id: versionId }),
          append,
          dry_run: dry,
        });
      }}
      canApply={(p) => p.can_write && p.twins > 0}
      applyLabel={(p) => `Write ${p.twins} twin(s)`}
      describe={rebuildSummary}
      detail={(p) => <RebuildPlanView plan={p} rate={run.pln_per_usd} />}
      fields={
        <>
        {versions && !versions.length ? (
          <p className="banner-warn">
            This project has no published process, so the rebuild is refused. Publish one
            on <Link to={`/projects/${run.project_id}?tab=Process`}>the project's Process tab</Link>.
          </p>
        ) : null}
        <FieldGrid>
          <Field label="Process version"
            hint={append ? "An append takes the batch's own version." : "The steps the twins can take."}>
            <select className="text" value={versionId ?? ""} disabled={append}
              onChange={(e) => setVersionId(Number(e.target.value) || null)}>
              {versionId === null ? <option value="">— none —</option> : null}
              {(versions ?? []).map((v) => (
                <option key={v.id} value={v.id}>v{v.version_no} · {v.comment.slice(0, 60)}</option>
              ))}
            </select>
          </Field>
          <Field group label="Which devices"
            hint={pinned === null ? "A batch with no twins takes them all first." : "Clear it only after an undo."}>
            <CheckField checked={append} disabled={pinned === null} onChange={setAppend}>
              Only the devices that joined since the rebuild
            </CheckField>
          </Field>
          <Field wide
            label={<>Advanced (JSON) <InfoTip label="About the advanced inputs">
              <b>assume</b>: steps that happened, though no record proves it. A list of step keys names every
              device. An object gives each step device_ids, codes, since and until.<br />
              <b>since, until</b>: step key to date, the short form of a date range for a stated step.<br />
              <b>draw</b>: the stated steps whose parts came from our stock.<br />
              <b>costs</b>: plan key to the step keys a position paid for.<br />
              <b>spares</b>: {"[{qty, done, note}]"}, unnamed units on the shelf and the steps they took.<br />
              <b>settle</b>: {"[{step, part, how}]"}, one statement per difference in parts. how is draw, short,
              return or loss.<br />
              <b>tolerance</b>: the difference in pieces that needs no statement.<br />
              <b>active</b>: the devices still in work, as device_ids, codes, since and until.<br />
              <b>origins</b>: {"[{from_run_id, device_ids, codes, since, until}]"}, devices built on boards of another
              batch. That batch must be rebuilt first.
            </InfoTip></>}
            error={parsed.error}
            hint={`Optional. One object with any of: ${REBUILD_ADVANCED_KEYS.join(", ")}.`}>
            <AutoTextarea className="text mono" value={advanced} placeholder={'{"assume": ["label"], "tolerance": 2}'}
              onChange={(e) => setAdvanced(e.target.value)} />
          </Field>
        </FieldGrid>
        </>
      }
    />
  );
}

/** Take a rebuild back, with the live clicks that stand on its twins (decision
 *  0075 §8). Nothing is left to take back on a batch crafted live, and Apply says
 *  so by staying off. */
export function UndoRebuildDialog({ run, onClose }: { run: RunInfo; onClose: (c: boolean) => void }) {
  return (
    <DryRunDialog<RebuildUndoPlan>
      wide
      title="Undo rebuild"
      intro={`This takes back the rebuild of ${run.label}: first the live clicks that stand on its twins, newest first, then the rebuild itself. Read the list before you apply it.`}
      onClose={onClose}
      run={(dry) => undoRebuildRun(run.id, dry)}
      canApply={(p) => !p.refused.length && (p.clicks > 0 || p.rebuild_batches.length > 0)}
      applyLabel={() => "Undo the rebuild"}
      describe={(p) => (p.clicks || p.rebuild_batches.length
        ? <>{p.clicks} rebuilt click(s) and {p.twins} twin(s), {p.rebuild_batches.length} journal batch(es).</>
        : <>This batch has no rebuild to undo.</>)}
      detail={(p) => <RebuildUndoView plan={p} />}
      fields={null}
    />
  );
}

export type CraftModal =
  | { kind: "step"; target: Target; stepKey?: string }
  | { kind: "receive" } | { kind: "found" } | { kind: "finish" }
  | { kind: "scrap"; target: Target } | { kind: "merge"; ids: number[] }
  | { kind: "assembly" } | { kind: "link"; lineIds: number[]; label: string }
  | { kind: "repin" } | { kind: "reopen" } | { kind: "swap" } | { kind: "relink" };

/** Every dialog a crafted batch opens, in one place, for the tabs that open them.
 *  `ids` and `chosen` are the devices of the scan group. */
export function CraftModals({ modal, run, craft, ids, chosen, onClose, onCloseKeepGroup }: {
  modal: CraftModal | null;
  run: RunInfo;
  craft: Craft;
  ids: number[];
  chosen: "scanned" | "list";
  /** a dialog ended: `changed` means reload and empty the group */
  onClose: (changed: boolean) => void;
  /** a step ended: it keeps the group, so the next step can run on the same devices */
  onCloseKeepGroup: (changed: boolean) => void;
}) {
  const { view, draft, runs } = craft;
  if (!view || !modal) return null;
  const label = stepLabelOf(view);
  switch (modal.kind) {
    case "step":
      return <StepDialog run={run} view={view} target={modal.target} stepKey={modal.stepKey} onClose={onCloseKeepGroup} />;
    case "receive":
      return <ReceiveDialog run={run} boardsJlc={draft?.header.boards_jlc ?? null}
        orders={draft?.header.orders ?? []} onClose={onClose} />;
    case "found":
      return <FoundDialog run={run} view={view} runs={runs} onClose={onClose} />;
    case "finish":
      return (
        <DryRunDialog<{ units: number; refused: { unit: string; why: string[] }[] }>
          title="Mark finished"
          intro={`${ids.length} device(s), ${chosen === "scanned" ? "scanned" : "picked from the list"}. A device that misses a required step is refused.`}
          onClose={onClose}
          run={(dry) => craftFinish(run.id, { device_ids: ids, chosen, dry_run: dry })}
          describe={(p) => (p.refused.length
            ? <span className="banner-error">Refused: {refusedText(p.refused)}</span>
            : <>{p.units} device(s) can be marked finished.</>)}
          fields={null}
        />
      );
    case "scrap":
      return <ScrapDialog run={run} target={modal.target} onClose={onClose} />;
    case "merge":
      return <MergeDialog run={run} view={view} ids={modal.ids} label={label} onClose={onClose} />;
    case "assembly":
      return draft ? <AssemblyDialog run={run} draft={draft} onClose={onClose} /> : null;
    case "repin":
      return <RepinDialog run={run} view={view} onClose={onClose} />;
    case "reopen":
      return <ReopenDialog run={run} ids={ids} chosen={chosen} onClose={onClose} />;
    case "swap":
      return <SwapDialog run={run} view={view} id={ids[0]} label={label} onClose={onClose} />;
    case "relink":
      return <RelinkDialog run={run} view={view} id={ids[0]} onClose={onClose} />;
    case "link":
      return <LinkDialog run={run} view={view} lineIds={modal.lineIds} what={modal.label} onClose={onClose} />;
  }
}
